from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mac_shutdown_readonly_probe import PINS, prepare_candidate, safe_source, sha
from server_graceful_shutdown_candidate import prepare
from test_worker_resume_patch import PROOF_FIXTURE


class ShutdownProbeTests(unittest.TestCase):
    def test_fixed_preparers_compile_candidate_without_running_server(self):
        folder = Path(__file__).resolve().parent
        modules = {name: (folder / name).read_bytes() for name in PINS}
        self.assertEqual({name: sha(raw) for name, raw in modules.items()}, PINS)
        expected = sha(PROOF_FIXTURE)
        with patch('mac_shutdown_readonly_probe.EXPECTED_SERVER', expected):
            self.assertEqual(prepare_candidate(PROOF_FIXTURE, modules),
                             sha(prepare(PROOF_FIXTURE, expected)))

    def test_changed_source_refuses_without_importing_it(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            source = Path(temporary) / 'server.py'
            source.write_bytes(PROOF_FIXTURE)
            with patch('mac_shutdown_readonly_probe.EXPECTED_SERVER', sha(PROOF_FIXTURE)):
                self.assertEqual(safe_source(source), PROOF_FIXTURE)
                source.write_bytes(PROOF_FIXTURE + b'\n# modified')
                with self.assertRaisesRegex(ValueError, 'fingerprint_changed'):
                    safe_source(source)


if __name__ == '__main__':
    unittest.main()
