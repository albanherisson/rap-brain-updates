"""The unsigned repair is fixed to the published code, with no data members."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import io
import unittest
from zipfile import ZipFile

from build_manager_handoff_repair import build, HELPER_REPLACEMENTS
from manager_helper_inventory import HELPER_FILES


HERE = Path(__file__).resolve().parent
CAPABILITY = HERE.parent / 'manager-capability' / 'capability-1.zip'
NATIVE = HERE.parents[1] / 'beta14_inspection' / 'RapBrainManagerNative.swift'


class RepairBuildTests(unittest.TestCase):
    def test_published_baseline_only_and_no_user_data(self):
        before = hashlib.sha256(CAPABILITY.read_bytes()).hexdigest()
        result = build(CAPABILITY, NATIVE)
        self.assertEqual(set(result), {'app/launch_manager.py',
            'app/RapBrainManagerNative.swift', 'helper.zip'})
        self.assertEqual(hashlib.sha256(CAPABILITY.read_bytes()).hexdigest(), before)
        self.assertIn(b'return 42', result['app/launch_manager.py'])
        self.assertIn(b'proc.terminationStatus == 42',
                      result['app/RapBrainManagerNative.swift'])
        with ZipFile(CAPABILITY) as published:
            original_helper = published.read('helper.zip')
        with ZipFile(io.BytesIO(result['helper.zip'])) as helper, \
                ZipFile(io.BytesIO(original_helper)) as original:
            self.assertEqual(helper.namelist(), ['helper/' + name for name in HELPER_FILES])
            for name in HELPER_REPLACEMENTS:
                self.assertNotEqual(helper.read('helper/' + name),
                                    original.read('helper/' + name))

    def test_tampered_baseline_refused(self):
        with TemporaryDirectory(dir=HERE) as folder:
            fake = Path(folder) / 'capability.zip'
            fake.write_bytes(CAPABILITY.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'capability_changed'):
                build(fake, NATIVE)


if __name__ == '__main__':
    unittest.main()
