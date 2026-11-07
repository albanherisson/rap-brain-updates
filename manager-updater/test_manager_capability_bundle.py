"""The future Finder capability has one exact code-only candidate archive."""
import io
from pathlib import Path
import unittest
from zipfile import ZipFile

from beta14_one_click_candidate import prepare_launcher as creative_launcher
from beta14_one_click_candidate import prepare_dashboard as creative_dashboard
from creative_release import digest
from manager_capability_bundle import APP_CODE_FILES, assemble
from manager_helper_bundle import HELPER_FILES


OWNER_ARCHIVE = Path(__file__).resolve().parents[2] / 'evidence' / 'RapBrainManager_App_Beta14.zip'


class CapabilityBundleTests(unittest.TestCase):
    def test_exact_copy_candidate_is_deterministic_and_code_only(self):
        if not OWNER_ARCHIVE.is_file():
            self.skipTest('owner Beta 14 archive unavailable in this checkout')
        with ZipFile(OWNER_ARCHIVE) as original:
            launcher = original.read(next(name for name in original.namelist()
                                          if name.endswith('/launch_manager.py')))
            dashboard = original.read(next(name for name in original.namelist()
                                           if name.endswith('/dashboard_beta14.html')))
        inputs = (creative_launcher(launcher), creative_dashboard(dashboard))
        first, hashes, helper_hashes = assemble(*inputs)
        second, same_hashes, same_helper_hashes = assemble(*inputs)
        self.assertEqual((first, hashes, helper_hashes),
                         (second, same_hashes, same_helper_hashes))
        self.assertEqual(len(helper_hashes), len(HELPER_FILES))
        with ZipFile(io.BytesIO(first)) as archive:
            expected = sorted(['app/' + name for name in APP_CODE_FILES] +
                              ['helper.zip'])
            self.assertEqual(archive.namelist(), expected)
            self.assertTrue(all(digest(archive.read(name)) == hashes[name]
                                for name in expected))
            self.assertFalse(any('data/' in name or name.endswith(('.key', '.sqlite3'))
                                 for name in expected))
        with self.assertRaisesRegex(ValueError, 'baseline_changed'):
            assemble(inputs[0] + b'\n', inputs[1])


if __name__ == '__main__':
    unittest.main()
