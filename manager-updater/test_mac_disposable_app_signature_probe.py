"""The owner-side diagnostic names its stage without exposing app contents."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from mac_disposable_app_signature_probe import codesign


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


if __name__ == '__main__':
    unittest.main()
