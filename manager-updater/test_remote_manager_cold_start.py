import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "remote-development" / "signed-restart"),
    str(ROOT / "remote-development" / "ollama-reusable"),
    str(ROOT / "remote-development"),
]

import mac_manager_install_request as adapter
import mac_manager_start_request as startup


class ManagerStartTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.script = self.home / startup.SERVER
        self.script.parent.mkdir(parents=True)
        self.script.write_bytes(b"test server")
        self.task = {
            "schema": "rapbrain-remote-task-v5", "action": "manager_start", "id": "startup-test",
            "expected_server_sha256": hashlib.sha256(self.script.read_bytes()).hexdigest(),
            "expires_at": int(time.time()) + 120, "authorization_commit": "a" * 40,
        }
        self.request = startup.parse_start_task(self.task)

    def test_private_authorization_requires_exact_request(self):
        fetch = Mock(return_value=json.dumps(self.request).encode())
        startup.authorize_start(self.task, self.request, fetch=fetch, token=lambda: "fixture")
        fetch.assert_called_once_with("remote-development/manager-start-authorizations/startup-test.json",
                                      "fixture", "a" * 40)
        fetch.return_value = json.dumps(self.request | {"expected_server_sha256": "b" * 64}).encode()
        with self.assertRaisesRegex(ValueError, "authorization_mismatch"):
            startup.authorize_start(self.task, self.request, fetch=fetch, token=lambda: "fixture")
        with self.assertRaisesRegex(ValueError, "request_invalid"):
            startup.parse_start_task(self.task, now=self.task["expires_at"])

    def test_dashboard_reuses_verified_handoff_without_assuming_parent_arguments(self):
        installed = {"state": "committed", "attempt": "a" * 32}
        result = self.home / startup.HANDOFF_RECEIPT
        result.parent.mkdir(parents=True)
        result.parent.chmod(0o700)
        result.write_text(json.dumps(installed))
        result.chmod(0o600)
        endpoint = (self.home, {"port": 61234, "pid": 400})
        with patch.object(startup, "find_verified_dashboard", return_value=endpoint) as verify:
            self.assertEqual(startup.dashboard_endpoint(self.home, "process runner"), endpoint)
            verify.assert_called_once_with(self.home, installed["attempt"], "committed", call="process runner")
            verify.return_value = None
            self.assertIsNone(startup.dashboard_endpoint(self.home, "process runner"))
        result.unlink()
        with patch.object(startup, "find_verified_dashboard") as verify:
            self.assertIsNone(startup.dashboard_endpoint(self.home, "process runner"))
            verify.assert_not_called()

    def test_loopback_dashboard_is_accepted_only_with_the_private_receipt(self):
        receipt = {"state": "committed", "attempt": "a" * 32}
        handoff = self.home / startup.HANDOFF_RECEIPT
        handoff.parent.mkdir(parents=True, mode=0o700)
        handoff.write_text(json.dumps(receipt))
        handoff.chmod(0o600)
        runtime = self.home / "rapbrain-manager-beta-test"
        runtime.mkdir(mode=0o700)

        class ManagerHandler(BaseHTTPRequestHandler):
            current = receipt
            def do_GET(self):
                if self.path != "/api/rapbrain/manager-update-state":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(type(self).current).encode())

        manager = ThreadingHTTPServer(("127.0.0.1", 0), ManagerHandler)
        self.addCleanup(manager.server_close)
        thread = threading.Thread(target=manager.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(manager.shutdown)
        record = {"port": manager.server_port, "pid": os.getpid()}
        (runtime / "port.json").write_text(json.dumps(record))
        with patch.object(adapter, "runtime_directories", return_value=[runtime]):
            self.assertEqual(startup.dashboard_endpoint(self.home, "process runner"), (runtime, record))
            ManagerHandler.current = receipt | {"attempt": "b" * 32}
            self.assertIsNone(startup.dashboard_endpoint(self.home, "process runner"))

    def test_cold_start_reuses_the_manager_token_endpoint_and_confirms_health(self):
        token = "a" * 40
        http = Mock(side_effect=[f"const LAUNCH_TOKEN='{token}';".encode(), b'{"queued":true}'])
        wait = Mock(return_value=None)
        record = (self.home, {"port": 61234, "pid": 400})
        with patch.object(startup, "compatible_launcher", return_value=True), \
                patch.object(startup, "dashboard_endpoint", return_value=record), \
                patch.object(startup, "server_ready", side_effect=[False, True]):
            self.assertEqual(startup.start_server(self.home, self.request, http=http, await_manager=wait), "started")
        self.assertEqual(wait.call_args.args[0], self.home / startup.APP)
        self.assertEqual(http.call_count, 2)
        http.assert_called_with(61234, "POST", "/api/rapbrain/start", headers={"X-RB-Launch-Token": token})

    def test_already_running_opens_manager_without_enqueuing_a_second_server(self):
        http = Mock()
        with patch.object(startup, "server_ready", return_value=True), \
                patch.object(startup, "manager_launch_context", return_value=(61234, "local-token")) as manager:
            self.assertEqual(startup.start_server(self.home, self.request, http=http), "already_running")
            self.assertEqual(manager.call_args.args, (self.home,))
            manager.reset_mock()
            self.script.write_bytes(b"changed server")
            with self.assertRaisesRegex(ValueError, "server_changed"):
                startup.start_server(self.home, self.request, http=http)
            manager.assert_not_called()
        http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
