import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "remote-development" / "signed-restart"),
    str(ROOT / "remote-development" / "ollama-reusable"),
    str(ROOT / "remote-development"),
]

import mac_manager_lifecycle_request as lifecycle
import mac_signed_server_restart as signed


class ManagerLifecycleTest(unittest.TestCase):
    def test_process_inventory_keeps_running_children_and_excludes_exited_children(self):
        result = SimpleNamespace(returncode=0, stderr="", stdout=(
            "10 1 10 501 Ss /usr/bin/python3 -u /fixture/server.py\n"
            "11 10 10 501 Z+ (python3)\n"
            "12 10 10 501 S /usr/bin/python3 /fixture/server.py --worker\n"))
        with patch.object(signed, "command", return_value=result) as command:
            self.assertEqual(signed.process_rows(), {
                10: (1, 10, 501, "/usr/bin/python3 -u /fixture/server.py"),
                12: (10, 10, 501, "/usr/bin/python3 /fixture/server.py --worker")})
            self.assertIn("stat=", command.call_args.args[0][-1])

    @unittest.skipUnless(hasattr(os, "fork"), "requires POSIX waitpid")
    def test_exited_unreaped_child_does_not_block_exit_verification(self):
        child = os.fork()
        if child == 0:
            os._exit(0)
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                state = subprocess.run(["/bin/ps", "-p", str(child), "-o", "stat="],
                                       capture_output=True, text=True, check=True).stdout.strip()
                if state.startswith("Z"):
                    break
                time.sleep(0.02)
            self.assertTrue(state.startswith("Z"), state)
            self.assertNotIn(child, signed.process_rows())
        finally:
            os.waitpid(child, 0)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        (self.home / "Library/Application Support/RapBrainRemoteBridge").mkdir(parents=True, mode=0o700)
        self.script = self.home / lifecycle.SERVER
        self.script.parent.mkdir(parents=True)
        self.script.write_bytes(b"signed v33 test fixture")
        self.digest = hashlib.sha256(self.script.read_bytes()).hexdigest()
        self.task = {
            "schema": "rapbrain-remote-task-v6", "id": "lifecycle-test", "action": "manager_restart",
            "sequence": 33, "expected_server_sha256": self.digest, "manifest_sha256": "f" * 64,
            "release_commit": "a" * 40, "authorization_commit": "b" * 40,
            "expires_at": int(time.time()) + 120,
        }
        self.authorize = Mock()
        self.stop = Mock(return_value="stopped")
        self.manager = Mock()
        self.start = Mock(return_value="started")
        self.native = Mock(return_value={"state": "closed", "was_running": True, "window_present": False})
        self.show_window = Mock(return_value={"state": "running", "was_running": True, "window_present": True})

    def advance(self):
        return lifecycle.advance_lifecycle_task(self.task, home=self.home, authorize=self.authorize,
                                                stop=self.stop, launch_manager=self.manager, start=self.start,
                                                native=self.native, show_window=self.show_window)

    def test_reopen_closes_native_application_and_observes_the_new_window(self):
        self.task["action"] = "manager_reopen"
        order = []
        self.stop.side_effect = lambda *args, **kwargs: order.append("server_stopped") or "stopped"
        self.start.side_effect = lambda *args, **kwargs: order.append("server_started") or "started"
        self.native.side_effect = lambda *args, **kwargs: order.append("manager_closed") or {
            "state": "closed", "was_running": True, "window_present": False}
        self.show_window.side_effect = lambda *args, **kwargs: order.append("window_present")
        result = self.advance()
        self.assertEqual(order, ["window_present", "server_stopped", "manager_closed",
                                 "window_present", "server_started"])
        self.assertTrue(result["manager_closed"])
        self.assertTrue(result["manager_close_observed"])
        self.assertTrue(result["manager_reopened"])
        self.assertTrue(result["manager_window_present"])
        self.assertEqual(result["state"], "restarted")
        self.assertEqual(self.advance(), result)
        self.native.assert_called_once_with(self.home, "close")
        self.stop.assert_called_once()
        self.start.assert_called_once()

    def test_reopen_does_not_stop_the_server_if_its_initial_window_is_unverified(self):
        self.task["action"] = "manager_reopen"
        self.show_window.side_effect = ValueError("remote_manager_native_window_unverified")
        with self.assertRaisesRegex(ValueError, "window_unverified"):
            self.advance()
        self.stop.assert_not_called()
        self.native.assert_not_called()

    def test_authorization_binds_operation_manifest_and_commit(self):
        grant = lifecycle.parse_lifecycle_task(self.task)
        fetch = Mock(return_value=json.dumps(grant).encode())
        lifecycle.authorize_lifecycle(self.task, grant, fetch=fetch, token=lambda: "test-token")
        fetch.assert_called_once_with("remote-development/manager-lifecycle-authorizations/lifecycle-test.json",
                                      "test-token", "b" * 40)
        with self.assertRaisesRegex(ValueError, "authorization_mismatch"):
            lifecycle.authorize_lifecycle(self.task, grant | {"action": "manager_stop"},
                                          fetch=fetch, token=lambda: "test-token")
        self.authorize.side_effect = ValueError("authorization_mismatch")
        with self.assertRaisesRegex(ValueError, "authorization_mismatch"):
            self.advance()
        self.stop.assert_not_called()
        self.start.assert_not_called()

    def test_restart_waits_for_a_proven_manager_before_stopping(self):
        self.manager.side_effect = ValueError("remote_manager_dashboard_unverified")
        with self.assertRaisesRegex(ValueError, "dashboard_unverified"):
            self.advance()
        self.stop.assert_not_called()
        self.start.assert_not_called()

    def test_busy_worker_waits_then_restarts_the_same_release(self):
        self.stop.side_effect = [ValueError("jobs_active_or_unknown_status"), "stopped"]
        self.assertEqual(self.advance(), {"state": "pending"})
        self.start.assert_not_called()
        result = self.advance()
        self.assertEqual(result, {"state": "restarted", "stop": "stopped",
                                  "start": "started", "manager_verified": True})
        self.assertEqual(self.stop.call_args.args[1]["expected_server_sha256"], self.digest)
        self.assertEqual(self.stop.call_args.args[1]["release_commit"], "a" * 40)
        self.assertEqual(self.stop.call_args.kwargs, {"installed": True})
        self.assertEqual(self.advance(), result)
        self.assertEqual(self.stop.call_count, 2)
        self.start.assert_called_once()

    def test_recovery_retries_start_without_stopping_again(self):
        self.start.side_effect = [ValueError("remote_manager_start_health_unverified"), "started"]
        self.assertEqual(self.advance(), {"state": "pending"})
        self.assertEqual(self.advance()["state"], "restarted")
        self.assertEqual(self.start.call_count, 2)
        self.manager.assert_called_once()
        self.stop.assert_called_once()

    def test_stop_only_can_run_when_manager_is_closed(self):
        self.task["action"] = "manager_stop"
        self.assertEqual(self.advance(), {"state": "stopped"})
        self.assertEqual(self.advance(), {"state": "stopped"})
        self.stop.assert_called_once()
        self.manager.assert_not_called()
        self.start.assert_not_called()

    def test_installed_release_uses_signed_payload_and_pins_immutable_manifest(self):
        issued = int(time.time()) - 60
        raw = json.dumps({"signed_payload": {"issued_at": issued}}).encode()
        prior = "c" * 64
        manifest = {"sequence": 33, "required_server_sha256": prior,
                    "files": [{"path": "server.py", "payload_sha256": self.digest}]}
        receipt = Mock(return_value={"sequence": 33})
        release = SimpleNamespace(CHANNEL="https://example.test/main/manifest.json", fetch=Mock(return_value=raw),
                                  NoRedirect=Mock(), verify_manifest=Mock(return_value=manifest))
        recovery = SimpleNamespace(_private_json=receipt)
        strict = SimpleNamespace(parse_signed_json=json.loads)
        request = lifecycle.stop_request(lifecycle.parse_lifecycle_task(self.task))
        request["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
        with patch.dict(sys.modules, manager_update_release=release, pending_attempt_recovery=recovery,
                        strict_json=strict), patch.object(signed.urllib.request, "build_opener") as opener:
            opened = opener.return_value.open
            response = opened.return_value.__enter__.return_value
            response.status = 200
            response.geturl.side_effect = lambda: opened.call_args.args[0].full_url
            response.read.return_value = raw
            signed.verify_restart_release(request, self.home, self.script, installed_commit="a" * 40)
            self.assertTrue(response.geturl().endswith("/" + "a" * 40 + "/manager-stable/manifest.json"))
            release.fetch.assert_not_called()
            release.verify_manifest.assert_called_once_with(raw, minimum_sequence=32, now=issued)
            with self.assertRaisesRegex(ValueError, "baseline_mismatch"):
                signed.verify_restart_release(request, self.home, self.script)
            receipt.return_value = {"sequence": 32}
            with self.assertRaisesRegex(ValueError, "installed_sequence_mismatch"):
                signed.verify_restart_release(request, self.home, self.script, installed_commit="a" * 40)


if __name__ == "__main__":
    unittest.main()
