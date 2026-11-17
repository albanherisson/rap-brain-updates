import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "remote-development" / "signed-restart"),
    str(ROOT / "remote-development" / "ollama-reusable"),
    str(ROOT / "remote-development"),
]

import mac_manager_native as native


class ManagerNativeTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        self.app = self.home / native.APP
        self.app.mkdir(parents=True)
        self.signature = Mock(returncode=0)
        self.result = Mock(returncode=0, stdout=b'{"state":"closed","was_running":true,"window_present":false}')
        self.call = Mock(side_effect=[self.signature, self.result])
        accepted = patch.object(native, "compatible_launcher", return_value=True)
        accepted.start()
        self.addCleanup(accepted.stop)

    def test_graceful_close_targets_only_the_reviewed_app_path(self):
        self.assertEqual(native.native_request(self.home, "close", call=self.call),
                         {"state": "closed", "was_running": True, "window_present": False})
        first, second = self.call.call_args_list
        self.assertEqual(first.args[0], ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(self.app)])
        self.assertEqual(second.args[0][0], "/usr/bin/swift")
        self.assertEqual(json.loads(second.kwargs["input"]), {"app": str(self.app), "operation": "close"})

    def test_unverified_signature_blocks_native_operations(self):
        self.signature.returncode = 1
        with self.assertRaisesRegex(ValueError, "codesign_refused"):
            native.native_request(self.home, "close", call=self.call)
        self.assertEqual(self.call.call_count, 1)

    def test_missing_window_prevents_a_successful_reopen(self):
        self.result.stdout = b'{"state":"running","was_running":true,"window_present":false}'
        with self.assertRaisesRegex(ValueError, "window_unverified"):
            native.native_request(self.home, "open", call=self.call)

    def test_open_requires_a_verified_running_app_and_window(self):
        self.result.stdout = b'{"state":"running","was_running":true,"window_present":true}'
        result = native.native_request(self.home, "open", call=self.call)
        self.assertTrue(result["window_present"])
        command = self.call.call_args_list[-1]
        self.assertEqual(json.loads(command.kwargs["input"]), {"app": str(self.app), "operation": "open"})

    def test_native_launch_errors_remain_distinct_in_the_remote_receipt(self):
        self.result.returncode = 2
        self.result.stderr = b'remote_manager_native_launch_error_n10810'
        with self.assertRaisesRegex(ValueError, "launch_error_n10810"):
            native.native_request(self.home, "open", call=self.call)

    def test_unreviewed_error_text_is_not_published(self):
        self.result.returncode = 2
        self.result.stderr = b'Failed to launch /Users/private/path with sensitive context'
        with self.assertRaisesRegex(ValueError, "probe_failed"):
            native.native_request(self.home, "open", call=self.call)

    def test_open_uses_the_native_launch_operation(self):
        probe = Mock(return_value={"state": "running", "was_running": True, "window_present": True})
        self.assertTrue(native.open_native_window(self.home, inspect=probe)["window_present"])
        probe.assert_called_once_with(self.home, "open")

    def test_close_reply_cannot_report_a_still_running_application(self):
        self.result.stdout = b'{"state":"running","was_running":true,"window_present":true}'
        with self.assertRaisesRegex(ValueError, "exit_unverified"):
            native.native_request(self.home, "close", call=self.call)

    @unittest.skipUnless(sys.platform == "darwin", "requires AppKit and CoreGraphics")
    def test_native_source_typechecks_on_macos(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manager_window.swift"
            path.write_text(native.SWIFT, encoding="utf-8")
            result = subprocess.run(["/usr/bin/swiftc", "-typecheck", str(path)],
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
