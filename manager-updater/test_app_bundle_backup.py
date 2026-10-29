"""Restore the complete disposable app, including local code-signature bytes."""
from pathlib import Path
import tempfile
import unittest

from app_bundle_backup import read_app_backup, restore_app_backup, save_app_backup
from creative_release import Refused


class AppBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.app = root / 'Beta 14.app'
        resources = self.app / 'Contents' / 'Resources'
        resources.mkdir(parents=True)
        self.launcher = resources / 'launch_manager.py'
        self.launcher.write_bytes(b'original launcher')
        self.native = self.app / 'Contents' / 'MacOS' / 'RapBrainManagerLegacy'
        self.native.parent.mkdir()
        self.native.write_bytes(b'original signed executable')
        self.signature = self.app / 'Contents' / '_CodeSignature' / 'CodeResources'
        self.signature.parent.mkdir()
        self.signature.write_bytes(b'original signature')
        self.state = root / 'backups'
        self.state.mkdir(mode=0o700)

    def test_restores_original_signature_after_local_resign(self):
        expected = save_app_backup(self.app, self.state)
        self.assertEqual(read_app_backup(self.state), expected)
        self.launcher.write_bytes(b'new launcher')
        self.native.write_bytes(b'locally re-signed executable')
        self.signature.write_bytes(b'new signature')
        runtime = self.app / 'Contents' / 'Resources' / 'ed25519_runtime.py'
        runtime.write_bytes(b'new runtime')
        self.assertTrue(restore_app_backup(self.app, self.state,
            allowed_extra=('Contents/Resources/ed25519_runtime.py',)))
        self.assertEqual(self.launcher.read_bytes(), b'original launcher')
        self.assertEqual(self.native.read_bytes(), b'original signed executable')
        self.assertEqual(self.signature.read_bytes(), b'original signature')
        self.assertFalse(runtime.exists())

    def test_unexpected_new_file_refuses_before_restore(self):
        save_app_backup(self.app, self.state)
        self.launcher.write_bytes(b'new launcher')
        extra = self.app / 'Contents' / 'Resources' / 'user-note.txt'
        extra.write_bytes(b'preserve')
        with self.assertRaisesRegex(Refused, 'app_unexpected_extra_preserved'):
            restore_app_backup(self.app, self.state)
        self.assertEqual(extra.read_bytes(), b'preserve')
        self.assertEqual(self.launcher.read_bytes(), b'new launcher')

    def test_corrupt_backup_refuses_before_restore(self):
        save_app_backup(self.app, self.state)
        (self.state / 'app-original.app' / 'Contents' / 'MacOS' /
         'RapBrainManagerLegacy').write_bytes(b'corrupt')
        with self.assertRaisesRegex(Refused, 'app_backup_integrity'):
            restore_app_backup(self.app, self.state)
        self.assertEqual(self.native.read_bytes(), b'original signed executable')

    def test_symlink_app_member_refuses_backup(self):
        (self.app / 'Contents' / 'Resources' / 'outside').symlink_to(self.state)
        with self.assertRaisesRegex(Refused, 'app_bundle_unsafe_entry'):
            save_app_backup(self.app, self.state)


if __name__ == '__main__':
    unittest.main()
