"""Consolidated Mac probe uses pinned source and returns coarse inventory only."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mac_final_readonly_probe import PINS, coarse_process_inventory


class FinalProbeTests(unittest.TestCase):
    def test_every_public_preparer_matches_immutable_pin(self):
        for name, expected in PINS.items():
            raw = (Path(__file__).parent / name).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)

    def test_process_report_is_only_coarse_presence(self):
        source = Path('/Users/test/Downloads/rap-brain')
        resources = Path('/Users/test/Downloads/Beta14.app/Contents/Resources')
        ps = SimpleNamespace(returncode=0, stderr='', stdout=(
            '21 1 21 /usr/bin/python3 /Users/test/Downloads/rap-brain/server.py\n'
            '22 1 22 /usr/bin/python3 /Users/test/Downloads/Beta14.app/Contents/Resources/launch_manager.py\n'))
        listener = SimpleNamespace(returncode=0, stderr='', stdout='p21\n')
        with patch('mac_final_readonly_probe.subprocess.run', side_effect=[ps, listener]):
            report = coarse_process_inventory(source, resources)
        self.assertEqual(report, {'server_process_seen': True,
                                  'manager_process_seen': True,
                                  'port_8765_listening': True})

    def test_unavailable_listener_refuses(self):
        ps = SimpleNamespace(returncode=0, stderr='', stdout='21 1 21 /bin/zsh\n')
        listener = SimpleNamespace(returncode=2, stderr='failed', stdout='')
        with patch('mac_final_readonly_probe.subprocess.run', side_effect=[ps, listener]):
            with self.assertRaisesRegex(ValueError, 'listener_inventory_unavailable'):
                coarse_process_inventory(Path('/tmp/source'), Path('/tmp/app'))


if __name__ == '__main__':
    unittest.main()
