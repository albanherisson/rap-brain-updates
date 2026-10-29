"""Exercise the actual macOS codesign and exact app rollback on a copy."""
import plistlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from app_bundle_backup import inventory, restore_app_backup, save_app_backup
from mac_offline_bootstrap_gate import resign_verified_app, verify_restored_app


@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS codesign')
class MacAppSignatureIntegrationTests(unittest.TestCase):
    def test_sign_changed_bundle_then_restore_exact_signed_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'rap-brain'
            source.mkdir()
            app = root / 'Disposable Rap Brain.app'
            resources = app / 'Contents' / 'Resources'
            executable = app / 'Contents' / 'MacOS' / 'DisposableRapBrain'
            resources.mkdir(parents=True)
            executable.parent.mkdir()
            shutil.copy2('/bin/echo', executable)
            executable.chmod(0o755)
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
            folder = root / 'private-backup'
            folder.mkdir(mode=0o700)
            original = save_app_backup(app, folder)
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
