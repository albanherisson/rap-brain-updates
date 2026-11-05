"""Finder package imports the authenticated repair and rollback code."""
from pathlib import Path
import unittest

from build_first_bootstrap_app import dependencies
from build_manager_repair_app import ROOT, SCRIPT


class RepairFinderAppTests(unittest.TestCase):
    def test_bundled_dependency_closure_has_no_data_or_private_key(self):
        names = {path.name for path in dependencies(ROOT,
                                                    entry='manager_repair_installer')}
        self.assertTrue({'manager_repair_installer.py',
                         'manager_repair_rehearsal.py',
                         'manager_repair_release.py',
                         'manager_repair_transaction.py',
                         'app_bundle_backup.py',
                         'mac_offline_bootstrap_gate.py'} <= names)
        self.assertFalse(any('publisher_ed25519.key' in name or name.endswith('.sqlite3')
                             for name in names))
        self.assertIn('--install-signed', SCRIPT)


if __name__ == '__main__':
    unittest.main()
