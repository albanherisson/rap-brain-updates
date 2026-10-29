"""The owner-side diagnostic names its stage without exposing app contents."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mac_disposable_app_signature_probe import (
    codesign, copy_file_without_system_flags)


class DisposableAppProbeTests(unittest.TestCase):
    def test_codesign_failure_reports_stage_and_hides_home_path(self):
        app = Path.home() / 'Downloads' / 'Copied.app'
        failure = subprocess.CalledProcessError(1, 'codesign', stderr=(
            str(app) + ': code object is not signed').encode())
        with patch('mac_disposable_app_signature_probe.subprocess.run',
                   side_effect=failure):
            with self.assertRaisesRegex(ValueError,
                                        'original_copy_verify_codesign_failed') as caught:
                codesign(app, stage='original_copy_verify')
        self.assertNotIn(str(Path.home()), str(caught.exception))
        self.assertIn('<copie>', str(caught.exception))

    def test_copy_preserves_detached_signature_with_hex_xattr(self):
        with tempfile.TemporaryDirectory() as temp:
            original = Path(temp) / 'script'
            duplicate = Path(temp) / 'copy'
            original.write_bytes(b'#!/bin/sh\n')
            original.chmod(0o755)
            calls = []
            def native(argv, **kwargs):
                calls.append(argv)
                value = (b'com.apple.cs.CodeDirectory\n' if len(calls) == 1
                         else b'00 ff 10\n' if len(calls) == 2 else b'')
                return subprocess.CompletedProcess(argv, 0, value, b'')
            with patch('mac_disposable_app_signature_probe.subprocess.run',
                       side_effect=native):
                copy_file_without_system_flags(original, duplicate)
            self.assertEqual(duplicate.read_bytes(), original.read_bytes())
            self.assertEqual(duplicate.stat().st_mode & 0o777, 0o755)
            self.assertEqual(calls[2][1:4], ['-wx',
                'com.apple.cs.CodeDirectory', '00ff10'])


if __name__ == '__main__':
    unittest.main()
