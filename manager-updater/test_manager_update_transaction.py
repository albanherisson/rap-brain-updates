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
from app_bundle_backup import save_app_backup
from bootstrap_runtime_resources import RUNTIME_FILES
from manager_offline_lifecycle import MacOfflineManagerLifecycle
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
            'required_server_sha256': digest(self.before['server.py']),
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

    def test_handoff_reuses_existing_ticket_and_attempt(self):
        transaction = self.tx([True])
        with transaction.lifecycle.maintenance(self.source, self.launcher):
            result = self.tx([True]).install_handed_off(
                self.signed, self.archive, IDENTIFIER)
        self.assertEqual(result['state'], 'committed')
        self.assertEqual(result['backup_id'], IDENTIFIER)
        self.assert_code(self.after)
        self.assert_data()

    def test_handoff_refuses_without_parent_ticket(self):
        with self.assertRaises(Refused):
            self.tx([True]).install_handed_off(self.signed, self.archive,
                                               IDENTIFIER)
        self.assert_code(self.before)

    def test_handoff_never_recovers_another_pending_attempt(self):
        transaction = self.tx([True])
        record = {'id': '4' * 32, 'source': str(self.source),
            'launcher': str(self.launcher), 'schema': self.manifest['schema'],
            'sequence': 1, 'server_mode': 0o644,
            'server_baseline': digest(self.before['server.py']),
            'baselines': {entry['path']: entry['baseline_sha256']
                          for entry in self.manifest['files']}}
        (self.state / record['id']).mkdir(mode=0o700)
        transaction.record(record, 'preparing')
        with self.assertRaisesRegex(Refused, 'manager_other_attempt_pending'):
            transaction.install_handed_off(self.signed, self.archive, IDENTIFIER)
        self.assert_code(self.before)
        self.assert_data()

    def test_handoff_preserves_pending_attempt_if_saved_release_changed(self):
        transaction = self.tx([True])
        record = {'id': IDENTIFIER, 'source': str(self.source),
            'launcher': str(self.launcher), 'schema': self.manifest['schema'],
            'sequence': 1, 'server_mode': 0o644,
            'server_baseline': digest(self.before['server.py']),
            'baselines': {entry['path']: entry['baseline_sha256']
                          for entry in self.manifest['files']}}
        folder = self.state / IDENTIFIER
        folder.mkdir(mode=0o700)
        (folder / 'manager-release.json').write_bytes(b'different')
        transaction.record(record, 'preparing')
        with self.assertRaisesRegex(Refused, 'manager_original_release_changed'):
            transaction.install_handed_off(self.signed, self.archive, IDENTIFIER)
        self.assert_code(self.before)
        self.assert_data()

    def test_handoff_abort_restarts_unchanged_original(self):
        transaction = self.tx([True])
        with transaction.lifecycle.maintenance(self.source, self.launcher):
            result = self.tx([True]).abort_handoff_before_journal(
                self.signed, IDENTIFIER)
        self.assertEqual(result['state'], 'aborted')
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assertEqual(json.loads((self.state / 'manager-transaction.json')
                                    .read_text())['phase'], 'aborted')
        self.assert_code(self.before)
        self.assert_data()

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

    def test_offline_lifecycle_signs_and_clears_ticket_only_after_commit(self):
        (self.resources / 'dashboard_beta14.html').write_bytes(b'original dashboard')
        for name in RUNTIME_FILES:
            (self.resources / name).write_bytes(b'original signed resource')

        class Exited:
            def poll(self):
                return 0

        class Candidate:
            def __init__(self, source, state, supervisor, expected_server_sha256, *, port):
                self.expected_server_sha256 = expected_server_sha256
                self.lock = None
                self.current = None

            def start_and_check(self):
                self.lock.release_to_ticketed_candidate()
                self.current = Exited()
                return True

        inspector = lambda *_: {'server_process_seen': False,
            'manager_process_seen': False, 'port_8765_listening': False}
        lifecycle = MacOfflineManagerLifecycle(self.source, self.launcher,
            self.state, self.signed, pinned_key=self.pin, inspector=inspector,
            signer=lambda *_a, **_k: True,
            restored_verifier=lambda *_a, **_k: True,
            unchanged_verifier=lambda *_a, **_k: True,
            candidate_factory=Candidate)
        tx = ManagerUpdateTransaction(self.source, self.launcher, self.state,
                                      lifecycle, pinned_key=self.pin)
        result = tx.install(self.signed, self.archive)
        self.assertEqual(result['state'], 'committed')
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assertFalse((self.state / 'bootstrap-intent.json').exists())
        self.assert_code(self.after)
        self.assert_data()

    def test_offline_lifecycle_restores_old_app_after_failed_health(self):
        (self.resources / 'dashboard_beta14.html').write_bytes(b'original dashboard')
        for name in RUNTIME_FILES:
            (self.resources / name).write_bytes(b'original signed resource')
        outcomes = iter([False, True])
        checks = []

        class Exited:
            def poll(self): return 0

        class Candidate:
            def __init__(self, source, state, supervisor, expected_server_sha256, *, port):
                self.expected_server_sha256 = expected_server_sha256
                self.lock = None
                self.current = None

            def start_and_check(self):
                self.lock.release_to_ticketed_candidate()
                self.current = Exited()
                return next(outcomes)

        inspector = lambda *_: {'server_process_seen': False,
            'manager_process_seen': False, 'port_8765_listening': False}
        lifecycle = MacOfflineManagerLifecycle(self.source, self.launcher,
            self.state, self.signed, pinned_key=self.pin, inspector=inspector,
            signer=lambda *_a, **_k: checks.append('candidate') or True,
            restored_verifier=lambda *_a, **_k: checks.append('restored') or True,
            unchanged_verifier=lambda *_a, **_k: True,
            candidate_factory=Candidate)
        result = ManagerUpdateTransaction(self.source, self.launcher, self.state,
            lifecycle, pinned_key=self.pin).install(self.signed, self.archive)
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(checks, ['candidate', 'restored'])
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assert_code(self.before)
        self.assert_data()

    def test_unselected_app_change_refused_before_signing(self):
        dashboard = self.resources / 'dashboard_beta14.html'
        dashboard.write_bytes(b'original dashboard')
        for name in RUNTIME_FILES:
            (self.resources / name).write_bytes(b'original signed resource')
        folder = self.state / IDENTIFIER
        folder.mkdir(mode=0o700)
        save_app_backup(self.resources.parents[1], folder)
        (self.source / 'server.py').write_bytes(self.after['server.py'])
        self.launcher.write_bytes(self.after['app/launch_manager.py'])
        dashboard.write_bytes(b'unreviewed injected dashboard')
        called = []
        inspector = lambda *_: {'server_process_seen': False,
            'manager_process_seen': False, 'port_8765_listening': False}
        lifecycle = MacOfflineManagerLifecycle(self.source, self.launcher,
            self.state, self.signed, pinned_key=self.pin, inspector=inspector,
            signer=lambda *_a, **_k: called.append(True) or True)
        lifecycle.transaction_id = IDENTIFIER
        lifecycle.assert_stopped = lambda: None
        with self.assertRaises(Refused):
            lifecycle._sign()
        self.assertEqual(called, [])

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
