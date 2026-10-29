"""Complete bootstrap commit and rollback on disposable source/app/data."""
import base64
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from bootstrap_full_release import FILES, PRIMARY
from bootstrap_full_transaction import FullBootstrapTransaction
from bootstrap_runtime_resources import RUNTIME_FILES
from creative_release import Refused, canonical, digest
from offline_bootstrap_lifecycle import MacOfflineBootstrapLifecycle
from first_bootstrap_installer import install_from_channel
from test_bootstrap_transaction import OfflineFixture, IDENTIFIER


ROOT = Path(__file__).resolve().parent


class FullTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'source'
        data = self.source / 'data'
        data.mkdir(parents=True)
        self.app = root / 'Rap Brain Manager Beta 14.app'
        self.resources = self.app / 'Contents' / 'Resources'
        self.resources.mkdir(parents=True)
        executable = self.app / 'Contents' / 'MacOS' / 'RapBrainManagerLegacy'
        executable.parent.mkdir()
        executable.write_bytes(b'original native launcher and signature')
        signature = self.app / 'Contents' / '_CodeSignature' / 'CodeResources'
        signature.parent.mkdir()
        signature.write_bytes(b'original ad hoc signature')
        self.original_bundle = {executable.relative_to(self.app): executable.read_bytes(),
                                signature.relative_to(self.app): signature.read_bytes()}
        self.launcher = self.resources / 'launch_manager.py'
        self.before = {'server.py': b'original server\n',
                       'launch_manager.py': b'original launcher\n',
                       'dashboard_beta14.html': b'original dashboard\n'}
        self.after = {'server.py': b'guarded server\n',
                      'launch_manager.py': b'guarded launcher\n',
                      'dashboard_beta14.html': b'new dashboard\n'}
        self.after.update({name: (ROOT / name).read_bytes() for name in RUNTIME_FILES})
        (self.source / 'server.py').write_bytes(self.before['server.py'])
        (self.source / 'creative_engine.py').write_bytes(b'unchanged engine')
        for name in PRIMARY[1:]:
            (self.resources / name).write_bytes(self.before[name])
        (data / 'ollama_model.json').write_bytes(b'{"model":"fixture"}')
        (data / 'audio.wav').write_bytes(b'untouched')
        with sqlite3.connect(data / 'rapbrain.sqlite3') as con:
            con.execute('CREATE TABLE jobs (status TEXT)')
            con.execute("INSERT INTO jobs VALUES ('done')")
        self.saved_data = {p.name: p.read_bytes() for p in data.iterdir()}
        self.state = root / 'state'
        self.state.mkdir(mode=0o700)
        key = Ed25519PrivateKey.generate()
        pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.pin = digest(pub)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name in FILES:
                archive.writestr(name, self.after[name])
        self.archive = stream.getvalue()
        now = int(time.time())
        manifest = {'schema': 'rapbrain-guarded-bootstrap-v2',
            'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': {'isolated_rollback': 'passed', 'macos_runtime': 'passed'},
            'archive_url': 'https://albanherisson.github.io/rap-brain-updates/manager-bootstrap/guarded-1.zip',
            'archive_sha256': digest(self.archive), 'archive_bytes': len(self.archive),
            'runtime_sha256': {name: digest(self.after[name]) for name in RUNTIME_FILES}}
        for kind, path in zip(('server', 'launcher', 'dashboard'), PRIMARY):
            manifest['baseline_' + kind + '_sha256'] = digest(self.before[path])
            manifest['candidate_' + kind + '_sha256'] = digest(self.after[path])
        self.manifest = manifest
        self.signed = canonical({'signed_payload': manifest,
            'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(key.sign(canonical(manifest))).decode(),
            'public_key_base64': base64.b64encode(pub).decode()})

    def transaction(self, health):
        return FullBootstrapTransaction(self.source, self.launcher, self.state,
            OfflineFixture(self.state, health), pinned_key=self.pin)

    def prepared(self):
        return (patch('bootstrap_full_release.prepare_server',
                      return_value=self.after['server.py']),
                patch('bootstrap_full_release.prepare_launcher',
                      return_value=self.after['launch_manager.py']),
                patch('bootstrap_full_release.prepare_dashboard',
                      return_value=self.after['dashboard_beta14.html']))

    def assert_data_preserved(self):
        self.assertEqual(self.saved_data, {p.name: p.read_bytes()
                         for p in (self.source / 'data').iterdir()})

    def assert_app_signature_preserved(self):
        for name, raw in self.original_bundle.items():
            self.assertEqual((self.app / name).read_bytes(), raw)

    def test_signed_commit_installs_all_resources_without_data_changes(self):
        a, b, c = self.prepared()
        with a, b, c:
            result = self.transaction([True]).install(self.signed, self.archive)
        self.assertEqual(result['state'], 'committed')
        for name in FILES:
            path = self.source / name if name == 'server.py' else self.resources / name
            self.assertEqual(path.read_bytes(), self.after[name])
        self.assert_data_preserved()
        self.assert_app_signature_preserved()

    def test_failed_health_restores_originals_and_removes_runtime(self):
        a, b, c = self.prepared()
        with a, b, c:
            result = self.transaction([False, True]).install(self.signed, self.archive)
        self.assertEqual(result['state'], 'rolled_back')
        for name in PRIMARY:
            path = self.source / name if name == 'server.py' else self.resources / name
            self.assertEqual(path.read_bytes(), self.before[name])
        for name in RUNTIME_FILES:
            self.assertFalse((self.resources / name).exists())
        self.assert_data_preserved()
        self.assert_app_signature_preserved()

    def test_recovery_after_partial_switch_restores_original_pair_and_resources(self):
        self.test_signed_commit_installs_all_resources_without_data_changes()
        # Simulate a crash after some files changed, before the phase advanced.
        self.launcher.write_bytes(self.before['launch_manager.py'])
        (self.resources / RUNTIME_FILES[-1]).unlink()
        journal = self.state / 'bootstrap-transaction.json'
        record = json.loads(journal.read_text())
        record['phase'] = 'switch_pending'
        journal.write_text(json.dumps(record))
        journal.chmod(0o600)
        fixture = OfflineFixture(self.state, [True])
        with fixture.maintenance(self.source, self.launcher):
            a, b, c = self.prepared()
            with a, b, c:
                result = self.transaction([True]).recover()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assertEqual(self.launcher.read_bytes(), self.before['launch_manager.py'])
        self.assertFalse(any((self.resources / name).exists() for name in RUNTIME_FILES))
        self.assert_data_preserved()
        self.assert_app_signature_preserved()

    def test_offline_lifecycle_clears_ticket_only_after_terminal_commit(self):
        class ExitedCandidate:
            def poll(self):
                return 0

        class Candidate:
            def __init__(self, *_args, **_kwargs):
                self.lock = None
                self.current = None

            def start_and_check(self):
                self.lock.release_to_ticketed_candidate()
                self.current = ExitedCandidate()
                return True

        inspector = lambda *_: {'server_process_seen': False,
                                'manager_process_seen': False,
                                'port_8765_listening': False}
        signer = lambda *_args, **_kwargs: True
        lifecycle = MacOfflineBootstrapLifecycle(self.source, self.launcher,
            self.state, self.manifest, inspector=inspector, signer=signer,
            candidate_factory=Candidate)
        tx = FullBootstrapTransaction(self.source, self.launcher, self.state,
                                      lifecycle, pinned_key=self.pin)
        a, b, c = self.prepared()
        with a, b, c:
            result = tx.install(self.signed, self.archive)
        self.assertEqual(result['state'], 'committed')
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assertFalse((self.state / 'bootstrap-intent.json').exists())
        self.assert_data_preserved()

    def test_offline_lifecycle_restores_original_and_clears_ticket_on_failed_health(self):
        class Candidate:
            def __init__(self, *_args, **_kwargs):
                self.lock = None
                self.current = None

            def start_and_check(self):
                self.lock.release_to_ticketed_candidate()
                self.current = type('Exited', (), {'poll': lambda self: 1})()
                return False

        inspector = lambda *_: {'server_process_seen': False,
                                'manager_process_seen': False,
                                'port_8765_listening': False}
        lifecycle = MacOfflineBootstrapLifecycle(self.source, self.launcher,
            self.state, self.manifest, inspector=inspector,
            signer=lambda *_a, **_k: True,
            restored_verifier=lambda *_a, **_k: True,
            candidate_factory=Candidate)
        tx = FullBootstrapTransaction(self.source, self.launcher, self.state,
                                      lifecycle, pinned_key=self.pin)
        a, b, c = self.prepared()
        with a, b, c:
            result = tx.install(self.signed, self.archive)
        self.assertEqual(result['state'], 'restored_stopped')
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assertEqual(self.launcher.read_bytes(), self.before['launch_manager.py'])
        self.assert_app_signature_preserved()
        self.assert_data_preserved()

    def test_active_owner_mac_state_refuses_before_attempt(self):
        inspector = lambda *_: {'server_process_seen': True,
                                'manager_process_seen': True,
                                'port_8765_listening': True}
        lifecycle = MacOfflineBootstrapLifecycle(self.source, self.launcher,
            self.state, self.manifest, inspector=inspector,
            signer=lambda *_a, **_k: True)
        tx = FullBootstrapTransaction(self.source, self.launcher, self.state,
                                      lifecycle, pinned_key=self.pin)
        a, b, c = self.prepared()
        with a, b, c:
            with self.assertRaisesRegex(ValueError, 'still_running'):
                tx.install(self.signed, self.archive)
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assert_data_preserved()

    def test_backup_failure_before_any_swap_clears_verified_original_attempt(self):
        inspector = lambda *_: {'server_process_seen': False,
                                'manager_process_seen': False,
                                'port_8765_listening': False}
        lifecycle = MacOfflineBootstrapLifecycle(self.source, self.launcher,
            self.state, self.manifest, inspector=inspector,
            unchanged_verifier=lambda *_a, **_k: True)
        tx = FullBootstrapTransaction(self.source, self.launcher, self.state,
                                      lifecycle, pinned_key=self.pin)
        a, b, c = self.prepared()
        with a, b, c, patch('bootstrap_full_transaction.save_app_backup',
                           side_effect=Refused('app_backup_failed')):
            with self.assertRaisesRegex(Refused, 'app_backup_failed'):
                tx.install(self.signed, self.archive)
        self.assertEqual(json.loads((self.state / 'bootstrap-transaction.json').read_text())
                         ['phase'], 'restored_stopped')
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assert_app_signature_preserved()
        self.assert_data_preserved()

    def test_external_installer_refuses_active_mac_before_download(self):
        downloader = Mock()
        inspector = lambda *_: {'server_process_seen': True,
                                'manager_process_seen': True,
                                'port_8765_listening': True}
        with self.assertRaisesRegex(Refused, 'still_running'):
            install_from_channel(self.source, self.launcher, self.state,
                inspector=inspector, downloader=downloader, pinned_key=self.pin)
        downloader.assert_not_called()
        self.assertFalse((self.state / 'bootstrap-intent.json').exists())

    def test_external_installer_passes_signed_bundle_to_transaction_on_copy(self):
        inspector = lambda *_: {'server_process_seen': False,
                                'manager_process_seen': False,
                                'port_8765_listening': False}
        downloader = Mock(return_value=(self.signed, self.archive, self.manifest))
        lifecycle_factory = lambda source, launcher, state, manifest, **kwargs: (
            OfflineFixture(state, [True]))
        a, b, c = self.prepared()
        with a, b, c:
            result = install_from_channel(self.source, self.launcher, self.state,
                inspector=inspector, downloader=downloader,
                lifecycle_factory=lifecycle_factory, pinned_key=self.pin)
        self.assertEqual(result['state'], 'committed')
        downloader.assert_called_once()
        self.assert_data_preserved()


if __name__ == '__main__':
    unittest.main()
