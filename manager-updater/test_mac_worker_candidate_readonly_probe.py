from pathlib import Path
import unittest

from mac_worker_candidate_readonly_probe import MODULES, compile_candidate, sha
from test_worker_server_patch import FIXTURE


class MacWorkerProbeTests(unittest.TestCase):
    def test_exact_pins_and_in_memory_compilation(self):
        root = Path(__file__).parent
        for name, expected in MODULES.items():
            self.assertEqual(sha((root / name).read_bytes()), expected)
        result = compile_candidate(
            FIXTURE, (root / 'server_lifetime_guard.py').read_bytes(),
            (root / 'server_worker_activity_candidate.py').read_bytes(), sha(FIXTURE))
        self.assertEqual(len(result), 64)

    def test_changed_server_is_refused_by_preparer(self):
        root = Path(__file__).parent
        with self.assertRaisesRegex(ValueError, 'unknown_server_baseline'):
            compile_candidate(
                FIXTURE, (root / 'server_lifetime_guard.py').read_bytes(),
                (root / 'server_worker_activity_candidate.py').read_bytes())


if __name__ == '__main__':
    unittest.main()
