import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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

    def test_dashboard_belongs_to_expected_manager(self):
        runtime = self.home / "rapbrain-manager-beta-probe"
        record = {"port": 61234, "pid": 400}
        launcher = self.home / startup.APP / startup.LAUNCHER

        def call(command, **kwargs):
            if command[0].endswith("lsof"):
                output = "p400\nf8\n"
            elif command[-1] == "ppid=":
                output = " 450\n"
            else:
                output = f"{os.getuid()}\t/usr/bin/python3 {launcher} --no-browser\n"
            return SimpleNamespace(stdout=output, stderr="", returncode=0)

        with patch.object(startup, "runtime_directories", return_value=[runtime]), \
                patch.object(startup, "dashboard_record", return_value=record):
            self.assertEqual(startup.dashboard_endpoint(self.home, call), (runtime, record))
            with patch.object(startup, "owns_process", return_value=False):
                self.assertIsNone(startup.dashboard_endpoint(self.home, call))

    def test_cold_start_reuses_the_manager_token_endpoint_and_confirms_health(self):
        token = "a" * 40
        http = Mock(side_effect=[f"const LAUNCH_TOKEN='{token}';".encode(), b'{"queued":true}'])
        wait = Mock(return_value=None)
        record = (self.home, {"port": 61234, "pid": 400})
        with patch.object(startup, "compatible_launcher", return_value=True), \
                patch.object(startup, "dashboard_endpoint", return_value=record), \
                patch.object(startup, "server_ready", side_effect=[False, False, True]):
            self.assertEqual(startup.start_server(self.home, self.request, http=http, await_manager=wait), "started")
        self.assertEqual(wait.call_args.args[0], self.home / startup.APP)
        self.assertEqual(http.call_count, 2)
        http.assert_called_with(61234, "POST", "/api/rapbrain/start", headers={"X-RB-Launch-Token": token})

    def test_already_running_and_changed_server_do_not_enqueue_start(self):
        http = Mock()
        wait = Mock()
        with patch.object(startup, "server_ready", return_value=True):
            self.assertEqual(startup.start_server(self.home, self.request, http=http, await_manager=wait), "already_running")
            self.script.write_bytes(b"changed server")
            with self.assertRaisesRegex(ValueError, "server_changed"):
                startup.start_server(self.home, self.request, http=http, await_manager=wait)
        http.assert_not_called()
        wait.assert_not_called()


if __name__ == "__main__":
    unittest.main()
