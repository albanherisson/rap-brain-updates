"""Owner-side preparation must pin all source and publish no private files."""
from pathlib import Path
import hashlib
import io
import json
import unittest
from zipfile import ZipFile

from build_first_bootstrap_app import dependencies
from mac_prepare_manager_repair import (CAPABILITY_SHA256, SOURCE_MANIFEST_SHA256,
                                        SOURCE_REF, zip_files)


ROOT = Path(__file__).resolve().parent


class PrepareRepairTests(unittest.TestCase):
    def test_fixed_source_inventory_matches_local_reviewed_code(self):
        names = {path.name for path in dependencies(ROOT,
                                                    entry='manager_repair_installer')}
        names.update(('build_first_bootstrap_app.py', 'build_manager_repair_app.py',
            'build_manager_handoff_repair.py', 'manager_repair_candidate.py',
            'manager_version_label_candidate.py', 'manager_locale_identity_candidate.py',
            'manager_native_handoff_candidate.py', 'manager_handoff_repair_candidate.py',
            'manager_capability_inventory.py', 'mac_sign_manager_capability.py',
            'python_bootstrap_selector.sh', 'verify_ed25519.swift',
            'manager_stable_update2_candidate.py'))
        names.update(path.name for path in dependencies(ROOT,
            entry='manager_update_rehearsal'))
        raw = json.dumps({n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
                          for n in sorted(names)}, sort_keys=True,
                         separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), SOURCE_MANIFEST_SHA256)
        self.assertEqual(len(SOURCE_REF), 40)
        self.assertEqual(hashlib.sha256((ROOT.parent / 'manager-capability' /
            'capability-1.zip').read_bytes()).hexdigest(), CAPABILITY_SHA256)

    def test_public_candidate_archive_has_exact_source_members(self):
        with ZipFile(io.BytesIO(zip_files({'app/launch_manager.py': b'code',
                'helper.zip': b'helper'}))) as archive:
            self.assertEqual(archive.namelist(), ['app/launch_manager.py',
                                                   'helper.zip'])
            self.assertFalse(any('key' in name or 'sqlite' in name
                                 for name in archive.namelist()))


if __name__ == '__main__':
    unittest.main()
