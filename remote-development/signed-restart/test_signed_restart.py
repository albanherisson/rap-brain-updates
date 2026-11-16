"""Exercises signed restart authorization on a disposable server and database."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import mac_signed_server_restart as restart
import mac_manager_install_request as adapter
from creative_release import Refused
from manager_remote_request import remote_directory, save_remote_receipt


class SignedRestartTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.state = self.home / "Downloads/RapBrainManagerBackups/secure-update"
        self.state.mkdir(parents=True, mode=0o700)
        self.source = self.home / "Downloads/rap-brain"
        self.database = self.source / "data" / "rapbrain.sqlite3"
        self.database.parent.mkdir(parents=True)
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE jobs(status TEXT)")
            db.execute("INSERT INTO jobs VALUES ('done')")
        self.script = self.source / "server.py"
        self.script.write_bytes(Path(os.environ["RAP_BRAIN_BASELINE_FILE"]).read_bytes())
        receipt = self.state / "manager-accepted.json"
        receipt.write_text('{"sequence":30}')
        receipt.chmod(0o600)
        self.manifest = Path(os.environ["RAP_BRAIN_RELEASE_FILE"]).read_bytes()
        self.request = {
            "sequence": 31, "expires_at": int(time.time()) + 60,
            "manifest_sha256": hashlib.sha256(self.manifest).hexdigest(),
            "expected_server_sha256": hashlib.sha256(self.script.read_bytes()).hexdigest(),
        }

    def test_signed_v31_authorizes_v30_and_rejects_tampered_code(self):
        with patch("manager_update_release.fetch", return_value=self.manifest):
            restart.verify_restart_release(self.request, self.state, self.script)
            self.script.write_text("modified server")
            with self.assertRaisesRegex(ValueError, "restart_server_version_changed"):
                restart.verify_restart_release(self.request, self.state, self.script)

    def test_manifest_changed_and_signature_wrong_are_distinct_refusals(self):
        envelope = json.loads(self.manifest)
        envelope["signed_payload"]["sequence"] = 32
        tampered = json.dumps(envelope).encode()
        with patch("manager_update_release.fetch", return_value=tampered):
            with self.assertRaisesRegex(ValueError, "restart_release_changed"):
                restart.verify_restart_release(self.request, self.state, self.script)
            with self.assertRaises(Refused):
                restart.verify_restart_release(self.request | {
                    "manifest_sha256": hashlib.sha256(tampered).hexdigest()
                }, self.state, self.script)

    def test_active_jobs_refuse_stop_and_remove_ticket(self):
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO jobs VALUES ('running')")
        disk = self.database.read_bytes()
        with patch("manager_update_release.fetch", return_value=self.manifest), \
             patch.object(restart, "listener", return_value=10), \
             patch.object(restart, "process_group", return_value=11), \
             patch.object(restart, "runtime_token", return_value="a"*64), \
             patch("process_start_identity.read_start", return_value="start"), \
             patch("authenticated_runtime_client.read_runtime_proof", return_value={"worker_pid": 11}), \
             patch.object(restart.http.client, "HTTPConnection") as connection:
            with self.assertRaisesRegex(Refused, "jobs_active"):
                restart.prepare_restart(self.home, self.request)
        connection.assert_not_called()
        self.assertFalse((self.state / "maintenance.ticket").exists())
        self.assertEqual(self.database.read_bytes(), disk)

    def test_stop_waits_for_exit_and_preserves_database(self):
        disk = self.database.read_bytes()
        with patch("manager_update_release.fetch", return_value=self.manifest), \
             patch.object(restart, "listener", side_effect=[10, None]), \
             patch.object(restart, "process_group", return_value=11), \
             patch.object(restart, "process_rows", return_value={}), \
             patch.object(restart, "runtime_token", return_value="a"*64), \
             patch("process_start_identity.read_start", return_value="start"), \
             patch("authenticated_runtime_client.read_runtime_proof", return_value={"worker_pid": 11}), \
             patch("authenticated_runtime_client.assert_owned_listener"), \
             patch.object(restart.http.client, "HTTPConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 202
            response.read.return_value = b'{"stopping":true}'
            self.assertEqual(restart.prepare_restart(self.home, self.request), "stopped")
        method, path = connection.return_value.request.call_args.args
        self.assertEqual((method, path), ("POST", "/api/manager-update-stop"))
        self.assertFalse((self.state / "maintenance.ticket").exists())
        self.assertEqual(self.database.read_bytes(), disk)

    def test_bridge_keeps_job_busy_request_and_resumes_after_stop(self):
        request = self.request | {"schema": "rapbrain-manager-install-v1",
                                  "id": "signed-restart-test"}
        task = request | {"schema": "rapbrain-remote-task-v3", "action": "manager_install",
                          "authorization_commit": "a" * 40}
        (self.home / "Library/Application Support/RapBrainRemoteBridge").mkdir(parents=True, mode=0o700)
        directory = remote_directory(self.home, create=True)
        save_remote_receipt(directory, request, "waiting_foreign_server")
        with patch.object(adapter, "save_remote_receipt", wraps=save_remote_receipt) as save:
            with patch.object(adapter, "restart_foreign_server",
                              side_effect=[ValueError("worker_busy_or_maintenance"), None]) as stop:
                for _ in range(2):
                    state = adapter.advance_install_task(task, home=self.home,
                                                         authorize=lambda *_: None, restart=stop)
                    self.assertEqual(state, {"state": "pending"})
            self.assertEqual(save.call_args.args[2], "server_released")
