"""Exercise the actual macOS codesign and exact app rollback on a copy."""
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from app_bundle_backup import inventory, restore_app_backup, save_app_backup
from bootstrap_full_transaction import FullBootstrapTransaction
from mac_disposable_app_signature_probe import (
    copy_file_without_system_flags, inventory as probe_inventory)
from mac_offline_bootstrap_gate import resign_verified_app, verify_restored_app
from offline_bootstrap_lifecycle import MacOfflineBootstrapLifecycle
from bootstrap_runtime_resources import RUNTIME_FILES
from manager_offline_lifecycle import MacOfflineManagerLifecycle
from manager_update_transaction import ManagerUpdateTransaction
from manager_capability_transaction import OfflineManagerCapability
from manager_capability_rehearsal import rehearse_on_copy as rehearse_capability
from build_manager_version_update import build as build_version_update
import test_bootstrap_full_transaction as full_fixture
import test_manager_capability_transaction as capability_fixture
import test_manager_update_transaction as manager_fixture


@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS codesign')
class MacAppSignatureIntegrationTests(unittest.TestCase):
    def test_version_label_update_signs_and_restores_current_capability_copy(self):
        import io
        from zipfile import ZipFile
        published = Path(__file__).resolve().parent.parent / 'manager-capability' / 'capability-1.zip'
        with ZipFile(published) as zipped:
            baseline = zipped.read('app/launch_manager.py')
        with ZipFile(io.BytesIO(build_version_update(published))) as zipped:
            candidate = zipped.read('app/launch_manager.py')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            source = root / 'rap-brain'
            source.mkdir()
            (source / 'server.py').write_bytes(b'# synthetic server\n')
            app = root / 'Manager.app'
            resources = app / 'Contents' / 'Resources'
            resources.mkdir(parents=True)
            native = app / 'Contents' / 'MacOS' / 'RapBrainManagerLegacy'
            native.parent.mkdir()
            native.write_bytes(Path('/bin/echo').read_bytes())
            native.chmod(0o755)
            (app / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'org.rapbrain.disposable-version-label',
                'CFBundleExecutable': native.name, 'CFBundleName': 'Disposable Manager',
                'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1'}))
            launcher = resources / 'launch_manager.py'
            launcher.write_bytes(baseline)
            subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-',
                            str(app)], check=True, capture_output=True)
            folder = root / 'backup'
            folder.mkdir(mode=0o700)
            original = save_app_backup(app, folder)
            launcher.write_bytes(candidate)
            offline = lambda *_: {'server_process_seen': False,
                                  'manager_process_seen': False,
                                  'port_8765_listening': False}
            self.assertTrue(resign_verified_app(app, folder, source, launcher,
                                                inspector=offline))
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                            str(app)], check=True, capture_output=True)
            self.assertTrue(restore_app_backup(app, folder))
            self.assertTrue(verify_restored_app(app, folder, source, launcher,
                                               inspector=offline))
            self.assertEqual(inventory(app), original)

    def test_one_time_capability_rehearses_on_owner_shape_copy(self):
        fixture = capability_fixture.CapabilityTransactionTests('test_commit_and_idempotent_reopen')
        fixture.setUp()
        try:
            native = fixture.app / 'Contents' / 'MacOS' / 'RapBrainManagerLegacy'
            native.write_bytes(Path('/bin/echo').read_bytes())
            native.chmod(0o755)
            subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-',
                            str(fixture.app)], check=True, capture_output=True)
            original = inventory(fixture.app)
            result = rehearse_capability(fixture.source, fixture.launcher,
                fixture.state, fixture.raw, fixture.archive,
                pinned_key=fixture.signed_fixture.pin)
            self.assertEqual(result['state'], 'passed')
            self.assertEqual(inventory(fixture.app), original)
            fixture.assert_data()
            self.assertFalse((fixture.state / 'manager-capability.json').exists())
        finally:
            fixture.doCleanups()

    def test_one_time_capability_signs_disposable_app(self):
        fixture = capability_fixture.CapabilityTransactionTests('test_commit_and_idempotent_reopen')
        fixture.setUp()
        try:
            native = fixture.app / 'Contents' / 'MacOS' / 'RapBrainManagerLegacy'
            native.write_bytes(Path('/bin/echo').read_bytes())
            native.chmod(0o755)
            subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-',
                            str(fixture.app)], check=True, capture_output=True)
            result = OfflineManagerCapability(
                fixture.source, fixture.launcher, fixture.state,
                inspector=fixture.offline,
                pinned_key=fixture.signed_fixture.pin).install(fixture.raw,
                                                               fixture.archive)
            self.assertEqual(result['state'], 'committed')
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                            str(fixture.app)], check=True, capture_output=True)
            fixture.assert_data()
        finally:
            fixture.doCleanups()

    def test_one_time_capability_signed_copy_and_exact_rollback(self):
        fixture = capability_fixture.CapabilityTransactionTests('test_commit_and_idempotent_reopen')
        fixture.setUp()
        try:
            native = fixture.app / 'Contents' / 'MacOS' / 'RapBrainManagerLegacy'
            native.write_bytes(Path('/bin/echo').read_bytes())
            native.chmod(0o755)
            subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-',
                            str(fixture.app)], check=True, capture_output=True)
            original = inventory(fixture.app)
            transaction = OfflineManagerCapability(
                fixture.source, fixture.launcher, fixture.state,
                inspector=fixture.offline, pinned_key=fixture.signed_fixture.pin,
                signer=lambda *_a, **_k: False)
            result = transaction.install(fixture.raw, fixture.archive)
            self.assertEqual(result['state'], 'rolled_back')
            self.assertEqual(inventory(fixture.app), original)
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                            str(fixture.app)], check=True, capture_output=True)
            fixture.assert_data()
            self.assertFalse((fixture.state / 'helper').exists())
            self.assertFalse((fixture.state / 'maintenance.ticket').exists())
        finally:
            fixture.doCleanups()

    def test_general_manager_failed_health_restores_signed_bundle(self):
        fixture = manager_fixture.ManagerTransactionTests(
            'test_failed_health_restores_exact_code')
        fixture.setUp()
        try:
            (fixture.resources / 'dashboard_beta14.html').write_bytes(b'original dashboard')
            for name in RUNTIME_FILES:
                (fixture.resources / name).write_bytes(b'original signed resource')
            app = fixture.resources.parents[1]
            (app / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'org.rapbrain.disposable-manager-update',
                'CFBundleExecutable': 'RapBrainManagerLegacy',
                'CFBundleName': 'Disposable Rap Brain',
                'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1',
            }))
            native = app / 'Contents' / 'MacOS' / 'RapBrainManagerLegacy'
            native.parent.mkdir()
            native.write_bytes(Path('/bin/echo').read_bytes())
            native.chmod(0o755)
            subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-',
                            str(app)], check=True, capture_output=True)
            original = inventory(app)

            class FailedCandidate:
                def __init__(self, _source, _state, _supervisor, expected_server_sha256,
                             *, port):
                    self.expected_server_sha256 = expected_server_sha256
                    self.lock = None
                    self.current = None

                def start_and_check(self):
                    self.lock.release_to_ticketed_candidate()
                    self.current = type('Exited', (), {'poll': lambda self: 1})()
                    return False

            offline = lambda *_: {'server_process_seen': False,
                                  'manager_process_seen': False,
                                  'port_8765_listening': False}
            lifecycle = MacOfflineManagerLifecycle(
                fixture.source, fixture.launcher, fixture.state,
                fixture.signed, pinned_key=fixture.pin,
                inspector=offline, candidate_factory=FailedCandidate)
            result = ManagerUpdateTransaction(
                fixture.source, fixture.launcher, fixture.state,
                lifecycle, pinned_key=fixture.pin).install(fixture.signed, fixture.archive)
            self.assertEqual(result['state'], 'restored_stopped')
            self.assertEqual(inventory(app), original)
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                            str(app)], check=True, capture_output=True)
            fixture.assert_code(fixture.before)
            fixture.assert_data()
            self.assertFalse((fixture.state / 'maintenance.ticket').exists())
        finally:
            fixture.doCleanups()

    def test_full_failed_health_restores_signed_bundle_and_disposable_data(self):
        fixture = full_fixture.FullTransactionTests('test_failed_health_restores_originals_and_removes_runtime')
        fixture.setUp()
        try:
            (fixture.app / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'org.rapbrain.disposable-full-rollback',
                'CFBundleExecutable': 'RapBrainManagerLegacy',
                'CFBundleName': 'Disposable Rap Brain',
                'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1',
            }))
            native = fixture.app / 'Contents' / 'MacOS' / 'RapBrainManagerLegacy'
            native.write_bytes(Path('/bin/echo').read_bytes())
            native.chmod(0o755)
            subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-',
                            str(fixture.app)], check=True, capture_output=True)
            original_app = inventory(fixture.app)
            original_engine = (fixture.source / 'creative_engine.py').read_bytes()

            class FailedCandidate:
                def __init__(self, *_args, **_kwargs):
                    self.lock = None
                    self.current = None

                def start_and_check(self):
                    self.lock.release_to_ticketed_candidate()
                    self.current = type('Exited', (), {'poll': lambda self: 1})()
                    return False

            offline = lambda *_: {'server_process_seen': False,
                                  'manager_process_seen': False,
                                  'port_8765_listening': False}
            lifecycle = MacOfflineBootstrapLifecycle(
                fixture.source, fixture.launcher, fixture.state,
                fixture.manifest, inspector=offline, candidate_factory=FailedCandidate)
            transaction = FullBootstrapTransaction(
                fixture.source, fixture.launcher, fixture.state, lifecycle,
                pinned_key=fixture.pin)
            a, b, c = fixture.prepared()
            with a, b, c:
                result = transaction.install(fixture.signed, fixture.archive)
            self.assertEqual(result['state'], 'restored_stopped')
            self.assertEqual(inventory(fixture.app), original_app)
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                            str(fixture.app)], check=True, capture_output=True)
            for name in fixture.before:
                path = (fixture.source / name if name == 'server.py'
                        else fixture.resources / name)
                self.assertEqual(path.read_bytes(), fixture.before[name])
            self.assertEqual((fixture.source / 'creative_engine.py').read_bytes(),
                             original_engine)
            fixture.assert_data_preserved()
            self.assertFalse((fixture.state / 'maintenance.ticket').exists())
        finally:
            fixture.doCleanups()

    def test_sign_changed_bundle_then_restore_exact_signed_original(self):
        # macOS /var is a symlink to /private/var; the production path guard
        # intentionally refuses symlinked ancestors. Keep the fixture in the
        # runner checkout just like the other transaction fixtures.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            source = root / 'rap-brain'
            source.mkdir()
            app = root / 'Disposable Rap Brain.app'
            resources = app / 'Contents' / 'Resources'
            executable = app / 'Contents' / 'MacOS' / 'DisposableRapBrain'
            resources.mkdir(parents=True)
            executable.parent.mkdir()
            # System binaries can carry restricted macOS flags that an
            # unprivileged CI runner cannot copy into a temporary bundle.
            executable.write_bytes(Path('/bin/echo').read_bytes())
            executable.chmod(0o755)
            helper = executable.with_name('DetachedHelper')
            helper.write_bytes(b'#!/bin/sh\nexit 0\n')
            helper.chmod(0o755)
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-',
                            str(helper)], check=True, capture_output=True)
            (app / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'org.rapbrain.disposable-codesign-test',
                'CFBundleExecutable': executable.name,
                'CFBundleName': 'Disposable Rap Brain',
                'CFBundlePackageType': 'APPL',
                'CFBundleVersion': '1',
            }))
            launcher = resources / 'launch_manager.py'
            launcher.write_bytes(b'print("original")\n')
            subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-',
                            str(app)], check=True, capture_output=True)
            helper_copy = root / 'DetachedHelperCopy'
            copy_file_without_system_flags(helper, helper_copy)
            subprocess.run(['/usr/bin/codesign', '--verify', '--strict',
                            str(helper_copy)], check=True, capture_output=True)
            self.assertIn('Contents/MacOS/DetachedHelper', probe_inventory(app))
            folder = root / 'private-backup'
            folder.mkdir(mode=0o700)
            original = save_app_backup(app, folder)
            saved_helper = (folder / 'app-original.app' / 'Contents' / 'MacOS' /
                            'DetachedHelper')
            subprocess.run(['/usr/bin/codesign', '--verify', '--strict',
                            str(saved_helper)], check=True, capture_output=True)
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                            str(folder / 'app-original.app')],
                           check=True, capture_output=True)
            offline = lambda *_: {'server_process_seen': False,
                                  'manager_process_seen': False,
                                  'port_8765_listening': False}
            launcher.write_bytes(b'print("candidate")\n')
            self.assertTrue(resign_verified_app(app, folder, source, launcher,
                                                inspector=offline))
            self.assertNotEqual(inventory(app), original)
            self.assertTrue(restore_app_backup(app, folder))
            self.assertTrue(verify_restored_app(app, folder, source, launcher,
                                                inspector=offline))
            self.assertEqual(inventory(app), original)


if __name__ == '__main__':
    unittest.main()
