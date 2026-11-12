import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import mac_manager_install_request as adapter
from mac_manager_install_request import (
    APP, HANDOFF_RECEIPT, advance_install_task, dashboard_ready, open_manager,
    parse_install_task, reopen_manager, wait_for_manager,
)
from manager_remote_request import (
    lock_remote_directory, queue_remote_request, remote_directory, save_remote_receipt, write_remote_json,
)


class ReopeningTest(unittest.TestCase):
    def test_launcher_distinguishes_signature_and_launchservices_refusals(self):
        with tempfile.TemporaryDirectory() as scratch:
            app = Path(scratch).resolve()
            calls = []
            def run(args, **_):
                calls.append(args)
                return subprocess.CompletedProcess(args, 1)
            with self.assertRaisesRegex(ValueError, "codesign_refused"):
                open_manager(app, call=run)
            self.assertEqual(len(calls), 1)
            calls.clear()
            def launch(args, **_):
                calls.append(args)
                return subprocess.CompletedProcess(args, int(args[0] == "/usr/bin/open"))
            with self.assertRaisesRegex(ValueError, "launchservices_refused"):
                open_manager(app, call=launch)
            self.assertEqual(calls[-1], ["/usr/bin/open", str(app)])

    def test_cold_open_uses_foreground_and_background_until_manager_responds(self):
        moment = 0.0
        calls = []
        app = Path("/test")
        def sleep(delay):
            nonlocal moment
            moment += delay
        def open_attempt(bundle, *, background):
            self.assertEqual(bundle, app)
            calls.append(background)
            raise ValueError("remote_manager_launchservices_refused")
        with patch.object(adapter, "open_manager", open_attempt):
            failure = wait_for_manager(app, open_attempt, lambda: moment >= 21,
                                       clock=lambda: moment, sleep=sleep)
        self.assertIsNone(failure)
        self.assertEqual(calls, [False, True])

    def test_existing_manager_can_consume_request_during_failed_open(self):
        with tempfile.TemporaryDirectory() as scratch:
            home = Path(scratch).resolve()
            (home / "Library/Application Support/RapBrainRemoteBridge").mkdir(parents=True)
            task = {"schema": "rapbrain-remote-task-v3", "action": "manager_install", "id": "test-cold",
                    "sequence": 19, "manifest_sha256": "a" * 64, "expected_server_sha256": "b" * 64,
                    "expires_at": int(time.time()) + 60, "authorization_commit": "c" * 40}
            request = parse_install_task(task)
            def open_existing(app):
                self.assertEqual(app, home / APP)
                directory = remote_directory(home)
                fd = lock_remote_directory(directory)
                try:
                    save_remote_receipt(directory, request, "up_to_date")
                finally:
                    os.close(fd)
                raise ValueError("remote_manager_launchservices_refused")
            with patch.object(adapter, "compatible_launcher", return_value=True):
                args = dict(home=home, authorize=lambda *_: None, opener=open_existing)
                self.assertEqual(advance_install_task(task, **args), {"state": "pending"})
                self.assertEqual(advance_install_task(task, **args), {"state": "up_to_date"})

    def test_open_acceptance_is_retried_until_dashboard_replies_twice(self):
        moment = 0.0
        opens = []
        receipt = ("a" * 32, "committed")

        def sleep(delay):
            nonlocal moment
            moment += delay

        def opened(app):
            opens.append(app)
            return True

        def probe(_home, attempt, state):
            self.assertEqual((attempt, state), receipt)
            return len(opens) == 2

        home = Path("/test")
        self.assertTrue(reopen_manager(home, *receipt, opener=opened, probe=probe,
                                      clock=lambda: moment, sleep=sleep))
        self.assertEqual(opens, [home / APP, home / APP])

    def test_unverified_reopening_keeps_the_install_receipt_and_is_terminal(self):
        with tempfile.TemporaryDirectory() as scratch:
            home = Path(scratch).resolve()
            (home / "Library/Application Support/RapBrainRemoteBridge").mkdir(parents=True)
            task = {"schema": "rapbrain-remote-task-v3", "action": "manager_install", "id": "test-open",
                    "sequence": 17, "manifest_sha256": "a" * 64, "expected_server_sha256": "b" * 64,
                    "expires_at": int(time.time()) + 60, "authorization_commit": "c" * 40}
            request = parse_install_task(task)
            directory = remote_directory(home, create=True)
            queue_remote_request(directory, request)
            attempt = "d" * 32
            save_remote_receipt(directory, request, "handoff", attempt=attempt)
            receipt = home / HANDOFF_RECEIPT
            receipt.parent.mkdir(parents=True)
            write_remote_json(receipt, {"attempt": attempt, "state": "committed"})
            calls = []
            def reopener(_home, identifier, state, *, opener):
                calls.append((identifier, state))
                os.close(lock_remote_directory(directory))
                return False
            args = dict(home=home, authorize=lambda *_: None, reopener=reopener)
            expected = {"state": "committed", "manager_reopened": False,
                        "reason": "remote_manager_dashboard_unverified"}
            self.assertEqual(advance_install_task(task, **args), expected)
            self.assertEqual(advance_install_task(task, **args), expected)
            self.assertEqual(calls, [(attempt, "committed")])

    def test_loopback_requires_live_pid_and_exact_private_receipt(self):
        with tempfile.TemporaryDirectory() as scratch:
            home = Path(scratch).resolve()
            attempt = "c" * 32
            calls = []
            expected = {"attempt": attempt, "state": "committed", "installation_performed": True}
            receipt = home / HANDOFF_RECEIPT
            receipt.parent.mkdir(parents=True)
            write_remote_json(receipt, expected)
            reply = dict(expected)
            class Status(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    calls.append(self.path)
                    raw = json.dumps(reply).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

                def log_message(self, *_):
                    pass

            with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Status) as server:
                listener = threading.Thread(target=server.serve_forever)
                listener.start()
                try:
                    port = server.server_port
                    runtime = home / "rapbrain-manager-beta-test"
                    runtime.mkdir(mode=0o700)
                    (runtime / "port.json").write_text(json.dumps({"port": port, "pid": 222}))
                    def process(args, **_):
                        self.assertEqual(args, ["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"])
                        return subprocess.CompletedProcess(args, 0, str(home) + "\n", "")
                    valid = dict(call=process, live=lambda pid: pid == 222)
                    self.assertTrue(dashboard_ready(home, attempt, "committed", **valid))
                    self.assertFalse(dashboard_ready(home, "f" * 32, "committed", **valid))
                    reply["installation_performed"] = False
                    self.assertFalse(dashboard_ready(home, attempt, "committed", **valid))
                    before = len(calls)
                    self.assertFalse(dashboard_ready(home, attempt, "committed", call=process, live=lambda _: False))
                    self.assertEqual(len(calls), before)
                finally:
                    server.shutdown()
                    listener.join()


if __name__ == "__main__":
    unittest.main()
