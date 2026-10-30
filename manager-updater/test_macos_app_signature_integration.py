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
import test_bootstrap_full_transaction as full_fixture


@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS codesign')
class MacAppSignatureIntegrationTests(unittest.TestCase):
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
