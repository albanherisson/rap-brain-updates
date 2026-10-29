from pathlib import Path
import unittest

from mac_combined_readonly_probe import PINS, prepare_pair, sha
from test_worker_resume_patch import PROOF_FIXTURE
from test_beta14_runtime_token_candidate import FIXTURE as LAUNCH_FIXTURE


class CombinedProbeTests(unittest.TestCase):
    def test_pinned_public_modules_and_in_memory_pair(self):
        root = Path(__file__).parent
        modules = {name: (root / name).read_bytes() for name in PINS}
        for name, expected in PINS.items():
            self.assertEqual(sha(modules[name]), expected)
        outputs = prepare_pair(PROOF_FIXTURE, LAUNCH_FIXTURE, modules,
                               expected_server=sha(PROOF_FIXTURE),
                               expected_launcher=sha(LAUNCH_FIXTURE))
        self.assertEqual(len(outputs), 2)
        self.assertTrue(all(len(digest) == 64 for digest in outputs))

    def test_changed_source_is_refused_without_fallback(self):
        root = Path(__file__).parent
        modules = {name: (root / name).read_bytes() for name in PINS}
        with self.assertRaisesRegex(ValueError, 'unknown_server_baseline'):
            prepare_pair(PROOF_FIXTURE, LAUNCH_FIXTURE, modules)


if __name__ == '__main__':
    unittest.main()
