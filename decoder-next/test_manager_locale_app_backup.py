"""Regression for the Finder icon that blocked the copy rehearsal."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parents[1] / 'manager-updater' / 'locale_v4'))
sys.path.insert(1, str(Path(__file__).parents[1] / 'manager-updater'))
from app_bundle_backup import read_app_backup
from creative_release import Refused


class FinderIconBackupTests(unittest.TestCase):
    def test_exact_icon_in_verified_app_backup_but_other_root_files_refused(self):
        entry = {'sha256': '0' * 64, 'mode': 0o644, 'bytes': 0, 'xattrs': {}}
        expected = {'Contents/Resources/launch_manager.py': entry,
                    'Icon\r': entry}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'app-original.app').mkdir()
            path = root / 'app-backup.json'
            path.write_text(json.dumps(expected))
            path.chmod(0o600)
            with patch('app_bundle_backup.inventory', return_value=expected):
                self.assertEqual(read_app_backup(root), expected)
            unexpected = dict(expected)
            unexpected['unreviewed-root-file'] = entry
            path.write_text(json.dumps(unexpected))
            with patch('app_bundle_backup.inventory', return_value=unexpected):
                with self.assertRaisesRegex(Refused, 'manifest_invalid'):
                    read_app_backup(root)


if __name__ == '__main__':
    unittest.main()
