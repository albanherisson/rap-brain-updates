"""Offline gate refuses the actual active-state shape observed on owner Mac."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from creative_release import Refused
from mac_offline_bootstrap_gate import assert_offline, resign_verified_app


class OfflineGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'rap-brain'
        self.source.mkdir()
        self.launcher = root / 'Beta 14.app' / 'Contents' / 'Resources' / 'launch_manager.py'
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_bytes(b'fixture')

    def test_running_server_manager_or_port_always_refuses(self):
        keys = ('server_process_seen', 'manager_process_seen', 'port_8765_listening')
        for active in keys:
            report = {key: key == active for key in keys}
            with self.assertRaisesRegex(Refused, 'still_running'):
                assert_offline(self.source, self.launcher,
                               inspector=lambda *_: report)

    def test_offline_only_when_all_evidence_absent(self):
        report = {'server_process_seen': False, 'manager_process_seen': False,
                  'port_8765_listening': False}
        self.assertTrue(assert_offline(self.source, self.launcher,
                                       inspector=lambda *_: report))

    def test_unknown_inventory_refuses(self):
        with self.assertRaisesRegex(Refused, 'offline_inventory_invalid'):
            assert_offline(self.source, self.launcher,
                           inspector=lambda *_: {'port_8765_listening': False})

    def test_signing_refuses_on_non_mac_and_without_backup(self):
        with patch('mac_offline_bootstrap_gate.sys.platform', 'linux'):
            with self.assertRaisesRegex(Refused, 'macos_required'):
                resign_verified_app(self.launcher.parents[2], self.source,
                                    self.source, self.launcher)
        with patch('mac_offline_bootstrap_gate.sys.platform', 'darwin'):
            with self.assertRaises(Exception):
                resign_verified_app(self.launcher.parents[2], self.source,
                                    self.source, self.launcher,
                                    inspector=lambda *_: {
                                        'server_process_seen': False,
                                        'manager_process_seen': False,
                                        'port_8765_listening': False})


if __name__ == '__main__':
    unittest.main()
