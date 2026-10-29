"""Signed transaction with real disposable HTTP parent and worker processes."""
import base64
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from authenticated_runtime_client import read_runtime_proof
from creative_release import Refused, canonical, digest
from creative_transaction import Transaction
from owned_graceful_stop import graceful_stop_owned
from prejournal_intent import begin_attempt
from server_graceful_shutdown_candidate import prepare
from test_guarded_server_graceful_exit import SOURCE
from worker_activity_gate import finish_maintenance


TOKEN = 'c' * 64
TICKET = b'b' * 64 + b'\n'
ATTEMPT = 'd' * 32


def started_child(source, home, ticket=None):
    environment = dict(os.environ, HOME=str(home), RB_UPDATE_PROBE_TOKEN=TOKEN,
                       PYTHONDONTWRITEBYTECODE='1')
    if ticket is not None:
        environment['RB_UPDATE_LAUNCH_TICKET'] = ticket[:-1].decode('ascii')
    child = subprocess.Popen([sys.executable, '-u', str(source / 'server.py')],
                             cwd=source, env=environment, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True, close_fds=True)
    ready, _, _ = select.select([child.stdout], [], [], 15)
    if not ready or not (line := child.stdout.readline().decode()).startswith('PORT:'):
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=3)
        child.stdout.close()
        child.stderr.close()
        raise Refused('disposable_server_not_ready')
    return child, int(line.removeprefix('PORT:'))


class FixtureLifecycle:
    """Only used inside a disposable path with synthetic OS inventory."""
    transaction_id = ATTEMPT

    def __init__(self, source, state, home, health):
        self.source, self.state, self.home = source, state, home
        self.server_hash = digest((source / 'server.py').read_bytes())
        self.health = iter(health)
        self.current, self.port = started_child(source, home)
        self.start = f'{self.current.pid}:fixture-start'
        self.lock = None
        self.healthy = False

    def stop_candidate(self):
        if self.current.poll() is None:
            self.lock = graceful_stop_owned(
                source=self.source, state=self.state, handle=self.current,
                recorded_start=self.start, recorded_server_sha256=self.server_hash,
                token=TOKEN, ticket=TICKET, port=self.port)
            self.current.stdout.close()
            self.current.stderr.close()

    def assert_stopped(self):
        if (self.lock is None or self.lock.fd is None or
                self.current.poll() is None):
            raise Refused('fixture_writers_not_stopped')

    def start_and_check(self):
        self.assert_stopped()
        self.lock.release_to_ticketed_candidate()
        self.current, self.port = started_child(self.source, self.home, TICKET)
        self.start = f'{self.current.pid}:fixture-start'
        deadline = time.monotonic() + 5
        while True:
            try:
                read_runtime_proof(self.port, TOKEN,
                                   expected_parent_pid=self.current.pid)
                break
            except Refused:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(.05)
        self.healthy = next(self.health)
        return self.healthy

    @contextmanager
    def maintenance(self, source):
        if Path(source) != self.source:
            raise Refused('wrong_fixture_source')
        begin_attempt(self.state, self.source, TICKET, self.transaction_id)
        self.stop_candidate()
        try:
            yield self
        finally:
            journal = self.state / 'transaction.json'
            if (journal.exists() and self.healthy and self.current.poll() is None and
                    json.loads(journal.read_text()).get('phase') in
                    ('committed', 'rolled_back', 'aborted')):
                finish_maintenance(self.state, TICKET,
                                   expected_transaction_id=self.transaction_id,
                                   owned_health_verified=True, require_intent=True)
            if self.lock is not None and self.lock.fd is not None:
                self.lock.__exit__(None, None, None)

    def cleanup(self):
        if self.current.poll() is None:
            os.killpg(self.current.pid, signal.SIGTERM)
            self.current.wait(timeout=3)
        self.current.stdout.close()
        self.current.stderr.close()


class SignedGracefulTests(unittest.TestCase):
    def test_commit_and_failed_health_rollback_preserve_data(self):
        for health, expected_phase in (([True], 'committed'),
                                       ([False, True], 'rolled_back')):
            with self.subTest(expected_phase=expected_phase):
                with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
                    root = Path(temporary)
                    home = root / 'home'
                    state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
                    state.mkdir(parents=True, mode=0o700)
                    source = root / 'source'
                    data = source / 'data'
                    data.mkdir(parents=True)
                    server = prepare(SOURCE, digest(SOURCE))
                    (source / 'server.py').write_bytes(server)
                    before, after = b'VALUE = 1\n', b'VALUE = 2\n'
                    (source / 'creative_engine.py').write_bytes(before)
                    (data / 'ollama_model.json').write_bytes(b'{"model":"fixture"}')
                    (data / 'audio.wav').write_bytes(b'untouched')
                    with sqlite3.connect(data / 'rapbrain.sqlite3') as con:
                        con.execute('CREATE TABLE jobs (status TEXT)')
                        con.execute("INSERT INTO jobs VALUES ('done')")
                    original_data = {p.name: p.read_bytes() for p in data.iterdir()}
                    archive_buf = io.BytesIO()
                    with zipfile.ZipFile(archive_buf, 'w') as archive:
                        archive.writestr('creative_engine.py', after)
                    payload = archive_buf.getvalue()
                    key = Ed25519PrivateKey.generate()
                    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
                    now = int(time.time())
                    manifest = {
                        'schema': 'rapbrain-creative-production-v1',
                        'component': 'creative_engine', 'target': 'creative_engine.py',
                        'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 3600,
                        'production_install_authorized': True,
                        'baseline_sha256': digest(before),
                        'required_server_sha256': digest(server),
                        'payload_sha256': digest(after), 'archive_sha256': digest(payload),
                        'archive_bytes': len(payload),
                        'archive_url': 'https://albanherisson.github.io/rap-brain-updates/creative-stable/engine-1.zip',
                        'data_migrations': [],
                        'validation': {'real_ollama': 'passed', 'full_server': 'passed'}}
                    signed = canonical({'signed_payload': manifest,
                                        'signature_algorithm': 'Ed25519',
                                        'signature_base64': base64.b64encode(
                                            key.sign(canonical(manifest))).decode(),
                                        'public_key_base64': base64.b64encode(pub).decode()})
                    lifecycle = FixtureLifecycle(source, state, home, health)
                    try:
                        with (patch('authenticated_runtime_client.assert_owned_listener',
                                    return_value=True),
                              patch('owned_graceful_stop.assert_owned_listener',
                                    return_value=True),
                              patch('runtime_evidence.require_live_owned_handle',
                                    side_effect=lambda handle, recorded: recorded),
                              patch('runtime_evidence.read_start',
                                    return_value='worker:fixture-start'),
                              patch('runtime_evidence.read_owned_group',
                                    side_effect=lambda *, manager_pid, parent_pid, worker_pid:
                                    frozenset((parent_pid, worker_pid))),
                              patch('owned_graceful_stop._assert_group_gone',
                                    return_value=None)):
                            transaction = Transaction(source, state, lifecycle,
                                                      pinned_key=digest(pub))
                            result = transaction.install(signed, payload)
                        self.assertEqual(result['state'], expected_phase)
                        self.assertEqual((source / 'creative_engine.py').read_bytes(),
                                         after if expected_phase == 'committed' else before)
                        self.assertEqual(original_data,
                                         {p.name: p.read_bytes() for p in data.iterdir()})
                        self.assertFalse((state / 'maintenance.ticket').exists())
                        self.assertEqual(json.loads((state / 'transaction.json').read_text())['id'],
                                         ATTEMPT)
                    finally:
                        lifecycle.cleanup()


if __name__ == '__main__':
    unittest.main()
