"""Pinned owner-copy inputs and isolated port selection stay reviewable."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from mac_full_copy_rehearsal import (
    PINS_SHA256, SWIFT_SHA256, digest, scoped_inspector)


ROOT = Path(__file__).parent


class FullCopyRehearsalTests(unittest.TestCase):
    def test_every_public_module_and_swift_verifier_is_pinned(self):
        raw = (ROOT / 'mac_full_copy_pins.json').read_bytes()
        self.assertEqual(digest(raw), PINS_SHA256)
        manifest = json.loads(raw)
        self.assertEqual(len(manifest['files']), 39)
        for name, expected in manifest['files'].items():
            self.assertEqual(digest((ROOT / name).read_bytes()), expected, name)
        self.assertEqual(digest((ROOT / 'verify_ed25519.swift').read_bytes()),
                         SWIFT_SHA256)

    def test_disposable_inspector_uses_selected_port_and_copy_paths(self):
        seen = []
        def run(argv, **_kwargs):
            seen.append(argv)
            if argv[0] == '/bin/ps':
                return subprocess.CompletedProcess(argv, 0,
                    '12 1 12 /usr/bin/python3 /owner/rap-brain/server.py\n', '')
            return subprocess.CompletedProcess(argv, 1, '', '')
        with patch('mac_full_copy_rehearsal.subprocess.run', side_effect=run):
            report = scoped_inspector(55443)(Path('/copies/rap-brain'),
                                               Path('/copies/app/Contents/Resources'))
        self.assertEqual(report, {'server_process_seen': False,
                                  'manager_process_seen': False,
                                  'port_8765_listening': False})
        self.assertIn('-iTCP:55443', seen[1])
        self.assertNotIn('-iTCP:8765', seen[1])


if __name__ == '__main__':
    unittest.main()
