import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

from mac_manager_install_request import (
    APP, DASHBOARD_LOG, HANDOFF_RECEIPT, LAUNCHER, advance_install_task,
    dashboard_ready, parse_install_task, reopen_manager,
)
from manager_remote_request import queue_remote_request, remote_directory, save_remote_receipt, write_remote_json


class ReopeningTest(unittest.TestCase):
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
                return False
            args = dict(home=home, authorize=lambda *_: None, reopener=reopener)
            expected = {"state": "committed", "manager_reopened": False,
                        "reason": "remote_manager_dashboard_unverified"}
            self.assertEqual(advance_install_task(task, **args), expected)
            self.assertEqual(advance_install_task(task, **args), expected)
            self.assertEqual(calls, [(attempt, "committed")])

    def test_loopback_requires_owned_listener_and_matching_attempt(self):
        with tempfile.TemporaryDirectory() as scratch:
            home = Path(scratch).resolve()
            launcher = home / APP / LAUNCHER
            attempt = "c" * 32
            calls = []
            class Status(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    calls.append(self.path)
                    raw = json.dumps({"attempt": attempt, "state": "committed"}).encode()
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
                    log = home / DASHBOARD_LOG
                    log.parent.mkdir(parents=True)
                    log.write_text(f"Tableau de bord : http://127.0.0.1:{port}/\n")
                    def process(args, **_):
                        uid = os.getuid()
                        if args[0] == "/usr/sbin/lsof":
                            out = "p222\nf3\n"
                        elif args[1:3] == ["-p", "222"]:
                            out = f"111 {uid}\n"
                        else:
                            out = f"{uid} /usr/bin/python3 {launcher} --candidate {launcher.parent / 'candidate'} --no-browser\n"
                        return subprocess.CompletedProcess(args, 0, out, "")
                    self.assertTrue(dashboard_ready(home, attempt, "committed", call=process))
                    self.assertFalse(dashboard_ready(home, "f" * 32, "committed", call=process))
                    before = len(calls)
                    def unowned(args, **_):
                        return subprocess.CompletedProcess(args, 0, "p222\np333\n", "")
                    self.assertFalse(dashboard_ready(home, attempt, "committed", call=unowned))
                    self.assertEqual(len(calls), before)
                finally:
                    server.shutdown()
                    listener.join()


if __name__ == "__main__":
    unittest.main()
