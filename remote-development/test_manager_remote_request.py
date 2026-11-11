import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from mac_manager_install_request import (APP, HANDOFF_RECEIPT, LAUNCHER, advance_install_task,
                                          authorize_install_task, parse_install_task)
from manager_remote_request import (decode_remote_json, queue_remote_request, remote_directory,
                                    remote_receipt, save_remote_receipt, write_remote_json)


class RemoteManagerRequestTest(unittest.TestCase):
    def task(self, **changes):
        return {"schema": "rapbrain-remote-task-v3", "id": "install-16",
                "action": "manager_install", "authorization_commit": "a" * 40,
                "sequence": 16, "manifest_sha256": "b" * 64, "expected_server_sha256": "c" * 64,
                "expires_at": int(time.time()) + 600, **changes}

    def home(self, root):
        home = Path(root).resolve()
        (home / "Library/Application Support/RapBrainRemoteBridge").mkdir(parents=True, mode=0o700)
        return home

    def test_private_authorization_precedes_local_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = self.home(temporary)
            task = self.task()
            def authorize(task, request):
                authorize_install_task(task, request, token=lambda: "test",
                    fetch=lambda path, token, commit: json.dumps(request | {"sequence": 17}).encode())
            with self.assertRaisesRegex(ValueError, "private_authorization_mismatch"):
                advance_install_task(task, home=home, authorize=authorize,
                                     opener=lambda _: self.fail("opened an unauthorized Manager"))
            self.assertIsNone(remote_directory(home))

    def test_invalid_input_and_expiration(self):
        for change in ({"command": "open"}, {"id": "../another"}, {"authorization_commit": "main"}):
            with self.assertRaises(ValueError):
                parse_install_task(self.task(**change))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            decode_remote_json(b'{"sequence":16,"sequence":17}')
        with tempfile.TemporaryDirectory() as temporary:
            home = self.home(temporary)
            result = advance_install_task(self.task(expires_at=1), home=home, authorize=lambda *_: None,
                                          opener=lambda _: self.fail("opened an expired task"))
            self.assertEqual(result, {"state": "expired"})
            self.assertFalse((remote_directory(home) / "request.json").exists())

    def test_waits_for_matching_terminal_receipt_and_opens_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = self.home(temporary)
            task = self.task()
            request = parse_install_task(task)
            directory = remote_directory(home, create=True)
            queue_remote_request(directory, request)
            attempt = "d" * 32
            save_remote_receipt(directory, request, "handoff", attempt=attempt)
            helper = home / HANDOFF_RECEIPT
            helper.parent.mkdir(parents=True)
            write_remote_json(helper, {"state": "committed", "attempt": "e" * 32})
            opens = []
            run = lambda: advance_install_task(task, home=home, authorize=lambda *_: None,
                                               opener=lambda app: opens.append(app) or True)
            self.assertEqual(run(), {"state": "pending"})
            write_remote_json(helper, {"state": "rolled_back", "attempt": attempt})
            self.assertEqual(run(), {"state": "rolled_back", "manager_reopened": True})
            self.assertEqual(run(), {"state": "rolled_back", "manager_reopened": True})
            self.assertEqual(opens, [home / APP])

    def test_foreign_server_restart_is_single_and_refusal_is_terminal(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temporary:
                home = self.home(temporary)
                task = self.task()
                request = parse_install_task(task)
                directory = remote_directory(home, create=True)
                queue_remote_request(directory, request)
                save_remote_receipt(directory, request, "waiting_foreign_server")
                calls = []
                def restart(home, request):
                    calls.append(request)
                    if fail:
                        raise ValueError("worker_busy_or_maintenance")
                run = lambda: advance_install_task(task, home=home, authorize=lambda *_: None,
                    opener=lambda _: self.fail("opened an already-running Manager"), restart=restart)
                expected = ({"state": "refused", "reason": "worker_busy_or_maintenance"}
                            if fail else {"state": "pending"})
                self.assertEqual(run(), expected)
                self.assertEqual(run(), expected)
                self.assertEqual(calls, [request])
                self.assertEqual(remote_receipt(directory, request)["state"], "refused" if fail else "server_released")

    def test_bootstrap_launcher_must_match_before_queue(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = self.home(temporary)
            launcher = home / APP / LAUNCHER
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(b"older Manager")
            result = advance_install_task(self.task(), home=home, authorize=lambda *_: None,
                                          opener=lambda _: self.fail("opened the old launcher"))
            self.assertEqual(result, {"state": "refused", "reason": "remote_manager_launcher_upgrade_required"})
            self.assertFalse((remote_directory(home) / "request.json").exists())


if __name__ == "__main__":
    unittest.main()
