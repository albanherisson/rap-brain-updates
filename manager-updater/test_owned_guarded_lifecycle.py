"""Exercise the prospective lifecycle with a real disposable HTTP worker."""
import base64
import io
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from creative_release import canonical, digest
from creative_transaction import Transaction
from owned_guarded_lifecycle import OwnedGuardedLifecycle
from recovery_start_guards import prepare_server
from test_guarded_server_graceful_exit import SOURCE
from test_signed_graceful_transaction import TOKEN, started_child


def fixture_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class OwnedLifecycleTests(unittest.TestCase):
    def test_signed_commit_and_health_failure_rollback(self):
        for fail_health, expected in ((False, 'committed'), (True, 'rolled_back')):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
                root = Path(temp)
                home = root / 'home'
                state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
                state.mkdir(parents=True, mode=0o700)
                source = root / 'source'
                data = source / 'data'
                data.mkdir(parents=True)
                port = fixture_port()
                fixture = SOURCE.replace(b"('127.0.0.1', 0)",
                    f"('127.0.0.1', {port})".encode()).replace(
                    b'    server = TCPServer(',
                    b'    TCPServer.allow_reuse_address = True\n    server = TCPServer(')
                server = prepare_server(fixture, digest(fixture))
                (source / 'server.py').write_bytes(server)
                before, after = b'VALUE = 1\n', b'VALUE = 2\n'
                (source / 'creative_engine.py').write_bytes(before)
                (data / 'ollama_model.json').write_bytes(b'{"model":"fixture"}')
                (data / 'audio.wav').write_bytes(b'untouched')
                with sqlite3.connect(data / 'rapbrain.sqlite3') as con:
                    con.execute('CREATE TABLE jobs (status TEXT)')
                    con.execute("INSERT INTO jobs VALUES ('done')")
                saved = {p.name: p.read_bytes() for p in data.iterdir()}
                archive_buf = io.BytesIO()
                with zipfile.ZipFile(archive_buf, 'w') as archive:
                    archive.writestr('creative_engine.py', after)
                archive = archive_buf.getvalue()
                key = Ed25519PrivateKey.generate()
                pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
                now = int(time.time())
                payload = {'schema': 'rapbrain-creative-production-v1',
                    'component': 'creative_engine', 'target': 'creative_engine.py',
                    'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 3600,
                    'production_install_authorized': True,
                    'baseline_sha256': digest(before),
                    'required_server_sha256': digest(server),
                    'payload_sha256': digest(after), 'archive_sha256': digest(archive),
                    'archive_bytes': len(archive),
                    'archive_url': 'https://albanherisson.github.io/rap-brain-updates/creative-stable/engine-1.zip',
                    'data_migrations': [],
                    'validation': {'real_ollama': 'passed', 'full_server': 'passed'}}
                signed = canonical({'signed_payload': payload,
                    'signature_algorithm': 'Ed25519',
                    'signature_base64': base64.b64encode(key.sign(canonical(payload))).decode(),
                    'public_key_base64': base64.b64encode(pub).decode()})
                original = None
                lifecycle = None
                previous_home = os.environ.get('HOME')
                try:
                    os.environ['HOME'] = str(home)
                    original, observed_port = started_child(source, home)
                    self.assertEqual(observed_port, port)
                    start = f'{original.pid}:fixture-start'
                    supervisor = {'process': original, 'runtime_token': TOKEN,
                                  'server_sha256': digest(server),
                                  'process_start_token': start}
                    lifecycle = OwnedGuardedLifecycle(source, state, supervisor,
                                                       digest(server), port=port)
                    if fail_health:
                        original_check = lifecycle._check_health
                        checks = [False]
                        def check(proc):
                            healthy = original_check(proc)
                            if not checks[0]:
                                checks[0] = True
                                lifecycle.healthy = False
                                return False
                            return healthy
                        lifecycle._check_health = check

                    def start_for(pid):
                        return f'{pid}:fixture-start'

                    with (patch('authenticated_runtime_client.assert_owned_listener', return_value=True),
                          patch('owned_graceful_stop.assert_owned_listener', return_value=True),
                          patch('owned_graceful_stop._assert_group_gone', return_value=None),
                          patch('runtime_evidence.require_live_owned_handle',
                                side_effect=lambda handle, recorded: recorded),
                          patch('runtime_evidence.read_start', side_effect=start_for),
                          patch('runtime_evidence.read_owned_group',
                                side_effect=lambda **kw: frozenset((kw['parent_pid'], kw['worker_pid']))),
                          patch('owned_supervisor_binding.require_live_owned_handle',
                                side_effect=lambda handle, recorded: recorded),
                          patch('owned_guarded_lifecycle.read_start', side_effect=start_for),
                          patch('owned_guarded_lifecycle.require_live_owned_handle',
                                side_effect=lambda handle, recorded: recorded),
                          patch('owned_guarded_lifecycle.read_owned_group', return_value=frozenset()),
                          patch('owned_guarded_lifecycle.require_no_local_listener', return_value=True)):
                        result = Transaction(source, state, lifecycle,
                                             pinned_key=digest(pub)).install(signed, archive)
                    self.assertEqual(result['state'], expected)
                    self.assertEqual((source / 'creative_engine.py').read_bytes(),
                                     before if fail_health else after)
                    self.assertEqual(saved, {p.name: p.read_bytes() for p in data.iterdir()})
                    self.assertFalse((state / 'maintenance.ticket').exists())
                    self.assertFalse((state / 'maintenance-intent.json').exists())
                finally:
                    processes = [original]
                    if lifecycle is not None:
                        processes.append(lifecycle.current)
                    for proc in processes:
                        if proc is None:
                            continue
                        if proc.poll() is None:
                            os.killpg(proc.pid, signal.SIGTERM)
                            proc.wait(timeout=3)
                        if proc.stdout is not None:
                            proc.stdout.close()
                        if proc.stderr is not None:
                            proc.stderr.close()
                    if previous_home is None:
                        os.environ.pop('HOME', None)
                    else:
                        os.environ['HOME'] = previous_home


if __name__ == '__main__':
    unittest.main()
