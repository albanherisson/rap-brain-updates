"""Signed bootstrap transaction mechanics on disposable files only."""
from contextlib import contextmanager
import base64
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from bootstrap_transaction import BootstrapTransaction
from creative_release import Refused, digest


IDENTIFIER = 'a' * 32


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
            phase = json.loads((self.state / 'bootstrap-transaction.json').read_text())['phase']
            if phase in ('committed', 'rolled_back', 'aborted') and not self.stopped:
                marker.unlink()
                (self.state / 'maintenance.ticket').unlink()

    @contextmanager
    def resume_maintenance(self, source, launcher, identifier):
        if identifier != self.transaction_id:
            raise ValueError('attempt_changed')
        with self.maintenance(source, launcher) as lease:
            yield lease

    def assert_stopped(self):
        if not self.stopped:
            raise ValueError('fixture_still_running')

    def stop_candidate(self):
        self.stopped = True

    def start_and_check(self):
        self.stopped = False
        return next(self.health)


class BootstrapTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'source'
        data = self.source / 'data'
        data.mkdir(parents=True)
        self.launcher = root / 'app' / 'launch_manager.py'
        self.launcher.parent.mkdir()
        self.before = {'server.py': b'original server\n',
                       'launch_manager.py': b'original launcher\n'}
        self.after = {'server.py': b'guarded server\n',
                      'launch_manager.py': b'guarded launcher\n'}
        (self.source / 'server.py').write_bytes(self.before['server.py'])
        (self.source / 'creative_engine.py').write_bytes(b'engine unchanged')
        self.launcher.write_bytes(self.before['launch_manager.py'])
        (data / 'ollama_model.json').write_bytes(b'{"model":"fixture"}')
        (data / 'audio.wav').write_bytes(b'untouched')
        with sqlite3.connect(data / 'rapbrain.sqlite3') as con:
            con.execute('CREATE TABLE jobs (status TEXT)')
            con.execute("INSERT INTO jobs VALUES ('done')")
        self.saved = {p.name: p.read_bytes() for p in data.iterdir()}
        self.state = root / 'state'
        self.state.mkdir(mode=0o700)
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.pin = digest(self.pub)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('server.py', self.after['server.py'])
            archive.writestr('launch_manager.py', self.after['launch_manager.py'])
        self.archive = buffer.getvalue()
        now = int(time.time())
        self.manifest = {'schema': 'rapbrain-guarded-bootstrap-v1',
            'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': {'isolated_rollback': 'passed', 'macos_runtime': 'passed'},
            'baseline_server_sha256': digest(self.before['server.py']),
            'baseline_launcher_sha256': digest(self.before['launch_manager.py']),
            'candidate_server_sha256': digest(self.after['server.py']),
            'candidate_launcher_sha256': digest(self.after['launch_manager.py']),
            'archive_sha256': digest(self.archive), 'archive_bytes': len(self.archive)}
        from creative_release import canonical
        self.signed = canonical({'signed_payload': self.manifest,
            'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(
                self.key.sign(canonical(self.manifest))).decode(),
            'public_key_base64': base64.b64encode(self.pub).decode()})

    def transaction(self, health):
        return BootstrapTransaction(self.source, self.launcher, self.state,
                                    OfflineFixture(self.state, health), pinned_key=self.pin)

    def install(self, health):
        with (patch('bootstrap_release.prepare_server', return_value=self.after['server.py']),
              patch('bootstrap_release.prepare_launcher',
                    return_value=self.after['launch_manager.py'])):
            result = self.transaction(health).install(self.signed, self.archive)
        self.assertEqual(self.saved, {p.name: p.read_bytes()
                                      for p in (self.source / 'data').iterdir()})
        self.assertFalse((self.state / 'bootstrap-intent.json').exists())
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        return result

    def test_healthy_commit_preserves_data(self):
        result = self.install([True])
        self.assertEqual(result['state'], 'committed')
        self.assertEqual((self.source / 'server.py').read_bytes(), self.after['server.py'])
        self.assertEqual(self.launcher.read_bytes(), self.after['launch_manager.py'])
        self.assertTrue((self.state / IDENTIFIER / 'backup.json').exists())

    def test_health_failure_restores_exact_originals(self):
        result = self.install([False, True])
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assertEqual(self.launcher.read_bytes(), self.before['launch_manager.py'])
        self.assertTrue((self.state / IDENTIFIER / 'backup.json').exists())

    def test_pending_pair_requires_original_attempt_and_restores_both(self):
        self.install([True])
        self.state.joinpath('bootstrap-intent.json').write_text(json.dumps({
            'id': IDENTIFIER, 'source': str(self.source), 'launcher': str(self.launcher),
            'ticket_sha256': hashlib.sha256(OfflineFixture.ticket).hexdigest()}))
        self.state.joinpath('maintenance.ticket').write_bytes(OfflineFixture.ticket)
        journal = self.state / 'bootstrap-transaction.json'
        record = json.loads(journal.read_text())
        record['phase'] = 'both_switched'
        journal.write_text(json.dumps(record))
        journal.chmod(0o600)
        with (patch('bootstrap_release.prepare_server', return_value=self.after['server.py']),
              patch('bootstrap_release.prepare_launcher',
                    return_value=self.after['launch_manager.py'])):
            result = self.transaction([True]).recover()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assertEqual(self.launcher.read_bytes(), self.before['launch_manager.py'])
        self.assertEqual(self.saved, {p.name: p.read_bytes()
                                      for p in (self.source / 'data').iterdir()})

    def test_interruption_between_server_and_launcher_restores_original_pair(self):
        self.install([True])
        (self.state / 'bootstrap-intent.json').write_text(json.dumps({
            'id': IDENTIFIER, 'source': str(self.source),
            'launcher': str(self.launcher),
            'ticket_sha256': hashlib.sha256(OfflineFixture.ticket).hexdigest()}))
        (self.state / 'bootstrap-intent.json').chmod(0o600)
        (self.state / 'maintenance.ticket').write_bytes(OfflineFixture.ticket)
        (self.state / 'maintenance.ticket').chmod(0o600)
        self.launcher.write_bytes(self.before['launch_manager.py'])
        journal = self.state / 'bootstrap-transaction.json'
        record = json.loads(journal.read_text())
        record['phase'] = 'server_switched'
        journal.write_text(json.dumps(record))
        journal.chmod(0o600)
        with (patch('bootstrap_release.prepare_server', return_value=self.after['server.py']),
              patch('bootstrap_release.prepare_launcher',
                    return_value=self.after['launch_manager.py'])):
            result = self.transaction([True]).recover()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assertEqual(self.launcher.read_bytes(), self.before['launch_manager.py'])
        self.assertEqual(self.saved, {p.name: p.read_bytes()
                                      for p in (self.source / 'data').iterdir()})

    def test_backup_failure_before_swap_restarts_originals(self):
        with (patch('bootstrap_release.prepare_server', return_value=self.after['server.py']),
              patch('bootstrap_release.prepare_launcher',
                    return_value=self.after['launch_manager.py']),
              patch('bootstrap_transaction.Transaction.backup',
                    side_effect=Refused('backup_failed'))):
            with self.assertRaisesRegex(Refused, 'backup_failed'):
                self.transaction([True]).install(self.signed, self.archive)
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assertEqual(self.launcher.read_bytes(), self.before['launch_manager.py'])
        self.assertEqual(json.loads((self.state / 'bootstrap-transaction.json').read_text())['phase'],
                         'aborted')
        self.assertFalse((self.state / 'maintenance.ticket').exists())

    def test_crash_during_partial_backup_recovers_without_reading_partial_files(self):
        # The updater stopped after writing the journal but before completing
        # the SQLite backup. A new run may safely restart unchanged originals.
        (self.state / 'bootstrap-intent.json').write_text(json.dumps({
            'id': IDENTIFIER, 'source': str(self.source),
            'launcher': str(self.launcher),
            'ticket_sha256': hashlib.sha256(OfflineFixture.ticket).hexdigest()}))
        (self.state / 'bootstrap-intent.json').chmod(0o600)
        (self.state / 'maintenance.ticket').write_bytes(OfflineFixture.ticket)
        (self.state / 'maintenance.ticket').chmod(0o600)
        (self.state / IDENTIFIER).mkdir(mode=0o700)
        (self.state / IDENTIFIER / 'bootstrap-release.json').write_bytes(b'incomplete')
        journal = self.state / 'bootstrap-transaction.json'
        journal.write_text(json.dumps({'id': IDENTIFIER, 'source': str(self.source),
            'launcher': str(self.launcher), 'modes': {'server.py': 0o644,
                'launch_manager.py': 0o644}, 'sequence': 1, 'phase': 'preparing',
            'baseline_server_sha256': digest(self.before['server.py']),
            'baseline_launcher_sha256': digest(self.before['launch_manager.py'])}))
        journal.chmod(0o600)
        result = self.transaction([True]).recover()
        self.assertEqual(result['state'], 'aborted')
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assertEqual(self.launcher.read_bytes(), self.before['launch_manager.py'])
        self.assertEqual(self.saved, {p.name: p.read_bytes()
                                      for p in (self.source / 'data').iterdir()})
        self.assertFalse((self.state / 'maintenance.ticket').exists())

    def test_bad_signature_refuses_before_offline_maintenance(self):
        changed = self.signed.replace(b'"sequence":1', b'"sequence":2')
        with self.assertRaises(ValueError):
            self.transaction([True]).install(changed, self.archive)
        self.assertFalse((self.state / 'bootstrap-intent.json').exists())
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assertEqual(self.launcher.read_bytes(), self.before['launch_manager.py'])

    def test_duplicate_terminal_journal_cannot_authorize_another_attempt(self):
        self.install([True])
        journal = self.state / 'bootstrap-transaction.json'
        raw = journal.read_text()
        journal.write_text(raw[:-1] + ',"phase":"committed"}')
        with self.assertRaisesRegex(Refused, 'bootstrap_journal_duplicate_field'):
            self.transaction([True]).recover()
        self.assertEqual((self.source / 'server.py').read_bytes(), self.after['server.py'])


if __name__ == '__main__':
    unittest.main()
