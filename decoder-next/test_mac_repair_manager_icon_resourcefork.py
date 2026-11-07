"""Disposable app test for preserving the oversized Finder icon on failure."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mac_repair_manager_icon_resourcefork as repair


class IconRepairTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.app = self.home / repair.APP_RELATIVE
        (self.app / 'Contents/Resources').mkdir(parents=True)
        (self.app / 'Contents/Resources/launch_manager.py').write_bytes(b'# unchanged\n')
        (self.app / 'Icon').write_bytes(b'')
        (self.home / 'Downloads/RapBrainManagerBackups/secure-update').mkdir(parents=True)
        self.forks = {str(self.app / 'Icon'): b'R' * 400_000}
        self.original = repair.fingerprint(self.app)

    def fake_run(self, argv, **_kwargs):
        command = argv[0]
        if command == '/usr/bin/codesign':
            return subprocess.CompletedProcess(argv, 0, b'', b'')
        if command == '/usr/bin/ditto':
            source, destination = Path(argv[-2]), Path(argv[-1])
            if source.is_dir():
                shutil.copytree(source, destination)
                old, new = str(source / 'Icon'), str(destination / 'Icon')
            else:
                shutil.copy2(source, destination)
                old, new = str(source), str(destination)
            if old in self.forks:
                self.forks[new] = self.forks[old]
            return subprocess.CompletedProcess(argv, 0, b'', b'')
        if command == '/usr/bin/xattr':
            if argv[1] == '-px':
                value = self.forks.get(argv[-1])
                return subprocess.CompletedProcess(argv, 0 if value else 1,
                                                   value.hex().encode() if value else b'', b'')
            if argv[1] == '-d':
                if argv[-1] not in self.forks:
                    return subprocess.CompletedProcess(argv, 1, b'', b'')
                del self.forks[argv[-1]]
                return subprocess.CompletedProcess(argv, 0, b'', b'')
            return subprocess.CompletedProcess(argv, 0,
                b'com.apple.ResourceFork\n' if argv[-1] in self.forks else b'', b'')
        raise AssertionError(argv)

    def fake_signed_backup_module(self, _app, _state, *, fail=False):
        def backup(app, folder):
            if fail:
                raise ValueError('copy_drill_failed')
            self.assertNotIn(str(app / 'Icon'), self.forks)
            self.assertEqual(repair.fingerprint(app), self.original)
        def inventory(app):
            self.assertNotIn(str(app / 'Icon'), self.forks)
            return repair.fingerprint(app)
        return backup, inventory

    def test_verified_copy_and_restore_precede_active_icon_change(self):
        with (patch.object(repair.sys, 'platform', 'darwin'),
              patch.object(repair, 'run', side_effect=self.fake_run),
              patch.object(repair, 'signed_backup_module',
                           side_effect=self.fake_signed_backup_module)):
            result = repair.repair(self.home)
        self.assertEqual(result['state'], 'repaired')
        self.assertEqual(repair.fingerprint(self.app), self.original)
        self.assertNotIn(str(self.app / 'Icon'), self.forks)
        self.assertEqual(self.forks[str(Path(result['backup']) / 'original.app/Icon')],
                         b'R' * 400_000)

    def test_copy_drill_failure_preserves_active_icon_fork(self):
        with (patch.object(repair.sys, 'platform', 'darwin'),
              patch.object(repair, 'run', side_effect=self.fake_run),
              patch.object(repair, 'signed_backup_module',
                           side_effect=lambda a, s: self.fake_signed_backup_module(a, s, fail=True))):
            with self.assertRaisesRegex(ValueError, 'copy_drill_failed'):
                repair.repair(self.home)
        self.assertEqual(self.forks[str(self.app / 'Icon')], b'R' * 400_000)
        self.assertEqual(repair.fingerprint(self.app), self.original)


if __name__ == '__main__':
    unittest.main()
