"""Deterministic helper candidate contains exactly reviewed code and no key."""
import hashlib
import io
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from creative_release import Refused, digest
from build_first_bootstrap_app import dependencies
from manager_helper_bundle import ROOT, HELPER_FILES, assemble


class HelperBundleTests(unittest.TestCase):
    def test_app_verifier_does_not_import_builder_or_source_packager(self):
        names = {path.name for path in dependencies(entry='manager_helper_release')}
        self.assertIn('manager_helper_release.py', names)
        self.assertIn('manager_helper_inventory.py', names)
        self.assertNotIn('manager_helper_bundle.py', names)
        self.assertNotIn('build_first_bootstrap_app.py', names)

    def test_deterministic_complete_candidate_has_no_private_key(self):
        first, hashes = assemble()
        second, again = assemble()
        self.assertEqual(first, second)
        self.assertEqual(hashes, again)
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(archive.namelist(),
                             ['helper/' + name for name in HELPER_FILES])
            self.assertTrue(all(digest(archive.read('helper/' + name)) == hashes[name]
                                for name in HELPER_FILES))
            self.assertFalse(any('key' in name and name.endswith(('.pem', '.key'))
                                 for name in archive.namelist()))

    def test_import_inventory_drift_refused_before_packaging(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            for name in HELPER_FILES:
                shutil.copyfile(ROOT / name, root / name)
            extra = ROOT / 'manager_helper_bundle.py'
            shutil.copyfile(extra, root / extra.name)
            target = root / 'manager_update_helper.py'
            target.write_text(target.read_text() +
                              '\nfrom manager_helper_bundle import assemble\n')
            with self.assertRaisesRegex(Refused,
                                        'manager_helper_import_inventory_changed'):
                assemble(root)


if __name__ == '__main__':
    unittest.main()
