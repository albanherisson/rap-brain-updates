"""Signed Manager update commit, failed health, replay and crash on copies."""
import base64
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from creative_release import Refused, canonical, digest
from manager_update_transaction import ManagerUpdateTransaction


IDENTIFIER = '3' * 32


class OfflineFixture:
    transaction_id = IDENTIFIER
    ticket = b'b' * 64 + b'\n'

    def __init__(self, state, health):
        self.state = state
        self.health = iter(health)
        self.stopped = True

    @contextmanager
    def maintenance(self, source, launcher):
        marker = self.state / 'bootstrap-intent.json'
        marker.write_text(json.dumps({'id': self.transaction_id,
            'source': str(source), 'launcher': str(launcher),
            'ticket_sha256': hashlib.sha256(self.ticket).hexdigest()}))
        marker.chmod(0o600)
        (self.state / 'maintenance.ticket').write_bytes(self.ticket)
        (self.state / 'maintenance.ticket').chmod(0o600)
        try:
            yield self
        finally:
            phase = json.loads((self.state / 'manager-transaction.json').read_text())['phase']
            if phase in ('committed', 'rolled_back', 'aborted'):
                marker.unlink(missing_ok=True)
                (self.state / 'maintenance.ticket').unlink(missing_ok=True)

    @contextmanager
    def resume_maintenance(self, source, launcher, identifier):
        if identifier != self.transaction_id:
            raise Refused('attempt_changed')
        with self.maintenance(source, launcher) as lease:
            yield lease

    def assert_stopped(self):
        if not self.stopped:
            raise Refused('fixture_still_running')

    def stop_candidate(self):
        self.stopped = True

    def start_and_check(self):
        self.stopped = False
        return next(self.health)


class ManagerTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'rap-brain'
        data = self.source / 'data'
        data.mkdir(parents=True)
        self.resources = root / 'Manager.app' / 'Contents' / 'Resources'
        self.resources.mkdir(parents=True)
        self.launcher = self.resources / 'launch_manager.py'
        self.before = {'server.py': b'original server\n',
                       'app/launch_manager.py': b'original launcher\n'}
        self.after = {'server.py': b'print("new server")\n',
                      'app/launch_manager.py': b'print("new launcher")\n'}
        (self.source / 'server.py').write_bytes(self.before['server.py'])
        self.launcher.write_bytes(self.before['app/launch_manager.py'])
        (self.source / 'creative_engine.py').write_bytes(b'original engine')
        (data / 'ollama_model.json').write_bytes(b'{"model":"fixture"}')
        (data / 'audio.wav').write_bytes(b'untouched')
        with sqlite3.connect(data / 'rapbrain.sqlite3') as con:
            con.execute('CREATE TABLE jobs (status TEXT)')
            con.execute("INSERT INTO jobs VALUES ('done')")
        self.data = {p.name: p.read_bytes() for p in data.iterdir()}
        self.state = root / 'state'
        self.state.mkdir(mode=0o700)
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.pin = digest(public)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name in sorted(self.after):
                archive.writestr(name, self.after[name])
        self.archive = stream.getvalue()
        now = int(time.time())
        self.manifest = {'schema': 'rapbrain-manager-production-v1',
            'sequence': 1, 'issued_at': now-1, 'expires_at': now+3600,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': {'macos_copy_install': 'passed', 'rollback': 'passed',
                           'runtime': 'passed'},
            'files': [{'path': name, 'baseline_sha256': digest(self.before[name]),
                       'payload_sha256': digest(self.after[name])}
                      for name in sorted(self.after)],
            'archive_url': ('https://raw.githubusercontent.com/albanherisson/'
                            'rap-brain-updates/main/manager-stable/update-1.zip'),
            'archive_sha256': digest(self.archive),
            'archive_bytes': len(self.archive)}
        self.signed = canonical({'signed_payload': self.manifest,
            'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(key.sign(
                canonical(self.manifest))).decode(),
            'public_key_base64': base64.b64encode(public).decode()})

    def tx(self, health):
        return ManagerUpdateTransaction(self.source, self.launcher, self.state,
                OfflineFixture(self.state, health), pinned_key=self.pin)

    def assert_data(self):
        self.assertEqual(self.data, {p.name: p.read_bytes()
            for p in (self.source / 'data').iterdir()})

    def assert_code(self, expected):
        self.assertEqual((self.source / 'server.py').read_bytes(), expected['server.py'])
        self.assertEqual(self.launcher.read_bytes(), expected['app/launch_manager.py'])

    def test_commit_backup_and_replay_refusal(self):
        result = self.tx([True]).install(self.signed, self.archive)
        self.assertEqual(result['state'], 'committed')
        self.assert_data()
        self.assert_code(self.after)
        self.assertTrue((self.state / IDENTIFIER / 'app-backup.json').is_file())
        self.assertTrue((self.state / IDENTIFIER / 'backup.json').is_file())
        with self.assertRaises(Refused):
            self.tx([True]).install(self.signed, self.archive)

    def test_no_lifecycle_refuses_before_any_write(self):
        transaction = ManagerUpdateTransaction(self.source, self.launcher,
                                               self.state, pinned_key=self.pin)
        with self.assertRaises(Refused):
            transaction.install(self.signed, self.archive)
        self.assertFalse((self.state / 'manager-transaction.json').exists())
        self.assert_code(self.before)

    def test_failed_health_restores_exact_code(self):
        result = self.tx([False, True]).install(self.signed, self.archive)
        self.assertEqual(result['state'], 'rolled_back')
        self.assert_code(self.before)
        self.assert_data()

    def test_other_update_incomplete_refuses_before_backup_or_swap(self):
        (self.state / 'transaction.json').write_text('{"phase":"switched"}')
        with self.assertRaises(Refused):
            self.tx([True]).install(self.signed, self.archive)
        self.assertFalse((self.state / 'manager-transaction.json').exists())
        self.assert_code(self.before)
        self.assert_data()

    def test_crash_during_switch_rolls_back_on_original_attempt(self):
        result = self.tx([True]).install(self.signed, self.archive)
        self.assertEqual(result['state'], 'committed')
        journal = self.state / 'manager-transaction.json'
        record = json.loads(journal.read_text())
        record['phase'] = 'switch_pending'
        journal.write_text(json.dumps(record))
        journal.chmod(0o600)
        self.launcher.write_bytes(self.before['app/launch_manager.py'])
        with self.tx([True]).lifecycle.maintenance(self.source, self.launcher):
            result = self.tx([True]).recover()
        self.assertEqual(result['state'], 'rolled_back')
        self.assert_code(self.before)
        self.assert_data()


if __name__ == '__main__':
    unittest.main()
