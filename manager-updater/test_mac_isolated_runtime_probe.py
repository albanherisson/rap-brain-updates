import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from mac_isolated_runtime_probe import MODULES, fetch, pinned_candidate


ROOT = Path(__file__).resolve().parent


class OwnerRuntimeProbeTests(unittest.TestCase):
    def test_exact_public_module_pins_match_local_sources(self):
        for name, expected in MODULES.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
                                 expected)

    def test_wrong_public_bytes_refuse_before_execution(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, limit):
                return b'raise RuntimeError("must not run")\n'

        with patch('mac_isolated_runtime_probe.urllib.request.urlopen',
                   return_value=Response()), self.assertRaisesRegex(
                       ValueError, 'public_module_changed'):
            fetch('https://example.invalid/module.py', '0' * 64)

    def test_candidate_hash_refusal_precedes_module_execution(self):
        class Probe:
            PINS = {}
            LAUNCHER = DASHBOARD = None

            def safe_source(self, path):
                return b'fixture'

            def prepare_all(self, *args):
                return ('not-the-pinned-candidate',)

        with self.assertRaisesRegex(ValueError, 'server_candidate_changed'):
            pinned_candidate(Probe(), b'fixture')
