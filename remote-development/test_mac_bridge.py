import base64
import json
import unittest

from mac_bridge import contents_url, keychain_token, read_queue, read_task, run, publish, watch_once
from mac_reviewed_test_trial import COMMIT, MANIFEST_SHA256, SERVER_SHA256, TEST_SHA256
from mac_manager_lab_trial import RUNNER_SHA256


TASK = {"schema": "rapbrain-remote-task-v1", "id": "pilot-001", "action": "health_check",
        "expected_server_sha256": "a" * 64}


def item(task):
    raw = json.dumps(task).encode()
    return {"type": "file", "encoding": "base64", "size": len(raw),
            "content": base64.b64encode(raw).decode()}


class BridgeTest(unittest.TestCase):
    def test_only_allowlisted_task(self):
        task, sha = read_task("pilot-001", get=lambda url: item(TASK))
        result = run(task, sha, probe=lambda: {"platform": "Darwin", "server_sha256": "a" * 64,
                                                "app_present": True, "manager_present": True,
                                                "git_available": True, "ollama_available": True})
        self.assertEqual(result["status"], "pass")
        self.assertNotIn("database", str(result))
        with self.assertRaisesRegex(ValueError, "Action"):
            read_task("pilot-001", get=lambda url: item({**TASK, "action": "shell"}))

    def test_rejects_path_and_duplicate_result(self):
        with self.assertRaises(ValueError):
            contents_url("tasks", "../other")
        with self.assertRaisesRegex(ValueError, "déjà publié"):
            publish("pilot-001", {}, "token", get=lambda url, **kwargs: {"type": "file"})

    def test_private_trial_requires_local_token_and_reports_only_counts(self):
        task = {**TASK, "action": "private_source_trial"}
        parsed, sha = read_task("pilot-001", get=lambda url: item(task))
        probe = lambda: {"platform": "Darwin", "server_sha256": "a" * 64,
                         "app_present": True, "manager_present": True,
                         "git_available": True, "ollama_available": True}
        called = []
        def fake_trial(token):
            called.append(token)
            return {"schema": "rapbrain-private-source-trial-v1", "status": "pass",
                    "source_commit": "b" * 40, "files_verified": 22,
                    "python_syntax_verified": 15, "bytes_verified": 374104,
                    "temporary_copy_removed": True, "installed_app_untouched": True}
        result = run(parsed, sha, probe=probe, private_probe=fake_trial,
                     private_token=lambda: "private test token")
        self.assertEqual(called, ["private test token"])
        self.assertEqual(result["private_source"]["files_verified"], 22)
        self.assertNotIn("private test token", str(result))
        bad_probe = lambda: {**probe(), "server_sha256": "c" * 64}
        called.clear()
        result = run(parsed, sha, probe=bad_probe, private_probe=fake_trial,
                     private_token=lambda: "private test token")
        self.assertEqual(result["status"], "version_mismatch")
        self.assertEqual(called, [])

    def test_versioned_source_validation_is_pinned_and_expires(self):
        candidate = {"schema": "rapbrain-remote-task-v2", "id": "pilot-006", "action": "source_validate",
                     "expected_server_sha256": "a" * 64, "source_commit": "b" * 40,
                     "manifest_sha256": "c" * 64, "candidate_server_sha256": "d" * 64,
                     "expires_at": 2000003600}
        task, sha = read_task("pilot-006", get=lambda url: item(candidate), now=2000000000)
        def probe():
            return {"platform": "Darwin", "server_sha256": "a" * 64,
                    "app_present": True, "manager_present": True,
                    "git_available": True, "ollama_available": True}
        called = []
        def fake_source(token, commit, manifest_sha, server_sha):
            called.append((token, commit, manifest_sha, server_sha))
            return {"schema": "rapbrain-private-source-trial-v1", "status": "pass",
                    "source_commit": commit, "manifest_sha256": manifest_sha,
                    "files_verified": 22, "python_syntax_verified": 15,
                    "bytes_verified": 374104, "temporary_copy_removed": True}
        result = run(task, sha, probe=probe, source_probe=fake_source,
                     private_token=lambda: "masked")
        self.assertEqual(len(called), 1)
        self.assertEqual(result["private_source"]["manifest_sha256"], "c" * 64)
        self.assertNotIn("masked", str(result))
        with self.assertRaisesRegex(ValueError, "expirée"):
            read_task("pilot-006", get=lambda url: item(candidate), now=2000003600)
        with self.assertRaisesRegex(ValueError, "Structure"):
            read_task("pilot-006", get=lambda url: item({**candidate, "command": "rm -rf /"}), now=2000000000)
        called.clear()
        run(task, sha, probe=lambda: {**probe(), "server_sha256": "e" * 64},
            source_probe=fake_source, private_token=lambda: "masked")
        self.assertEqual(called, [])

    def test_watch_publishes_once(self):
        calls = []
        queue = item({"schema": "rapbrain-remote-queue-v1", "task_id": "pilot-001"})
        def fake(url, method="GET", token=None, payload=None):
            calls.append((url, method))
            if method == "PUT":
                self.assertEqual(json.loads(payload)["branch"], "p0/remote-development-preflight")
                return {"content": {"path": "result"}}
            if "queue/current.json" in url:
                return queue
            if "tasks/pilot-001.json" in url:
                return item(TASK)
            return None
        probe = lambda: {"platform": "Darwin", "server_sha256": "a" * 64,
                         "app_present": True, "manager_present": True,
                         "git_available": True, "ollama_available": True}
        self.assertEqual(watch_once("token", get=fake, probe=probe), ("pilot-001", "pass"))
        self.assertEqual(sum(method == "PUT" for _, method in calls), 1)

    def test_reviewed_test_requires_exact_identity_and_reports_redacted_pass(self):
        candidate = {"schema": "rapbrain-remote-task-v2", "id": "pilot-009",
                     "action": "reviewed_test_trial", "expected_server_sha256": SERVER_SHA256,
                     "source_commit": COMMIT, "manifest_sha256": MANIFEST_SHA256,
                     "candidate_server_sha256": SERVER_SHA256, "expires_at": 2000003600}
        task, sha = read_task("pilot-009", get=lambda url: item(candidate), now=2000000000)
        probe = lambda: {"platform": "Darwin", "server_sha256": SERVER_SHA256,
                         "app_present": True, "manager_present": True,
                         "git_available": True, "ollama_available": True}
        calls = []
        def reviewed(token):
            calls.append(token)
            return {"schema": "rapbrain-private-source-trial-v1", "status": "pass",
                    "source_commit": COMMIT, "manifest_sha256": MANIFEST_SHA256,
                    "files_verified": 23, "python_syntax_verified": 16,
                    "bytes_verified": 374104, "temporary_copy_removed": True,
                    "reviewed_test": {"status": "pass", "tests_run": 2,
                                      "test_sha256": TEST_SHA256, "timeout_seconds": 20}}
        result = run(task, sha, probe=probe, reviewed_probe=reviewed,
                     private_token=lambda: "secret")
        self.assertEqual(calls, ["secret"])
        self.assertEqual(result["reviewed_test"]["tests_run"], 2)
        self.assertNotIn("secret", str(result))
        calls.clear()
        mismatch = run(task, sha, probe=lambda: {**probe(), "server_sha256": "0" * 64},
                       reviewed_probe=reviewed, private_token=lambda: "secret")
        self.assertEqual(mismatch["status"], "version_mismatch")
        self.assertEqual(calls, [])
        with self.assertRaisesRegex(ValueError, "Version des tests"):
            read_task("pilot-009", get=lambda url: item({**candidate, "source_commit": "b" * 40}),
                      now=2000000000)
        with self.assertRaisesRegex(ValueError, "expirée"):
            read_task("pilot-009", get=lambda url: item(candidate), now=2000003600)

    def test_manager_lab_requires_recovery_evidence_and_installed_hash(self):
        candidate = {"schema": "rapbrain-remote-task-v2", "id": "pilot-010",
                     "action": "manager_lab_trial", "expected_server_sha256": SERVER_SHA256,
                     "source_commit": COMMIT, "manifest_sha256": MANIFEST_SHA256,
                     "candidate_server_sha256": SERVER_SHA256, "expires_at": 2000003600}
        task, sha = read_task("pilot-010", get=lambda url: item(candidate), now=2000000000)
        probe = lambda: {"platform": "Darwin", "server_sha256": SERVER_SHA256,
                         "app_present": True, "manager_present": True,
                         "git_available": True, "ollama_available": True}
        calls = []
        def lab(token):
            calls.append(token)
            return {"schema": "rapbrain-private-source-trial-v1", "status": "pass",
                    "source_commit": COMMIT, "manifest_sha256": MANIFEST_SHA256,
                    "files_verified": 23, "python_syntax_verified": 16, "bytes_verified": 375259,
                    "temporary_copy_removed": True,
                    "manager_lab": {"status": "pass", "runner_sha256": RUNNER_SHA256,
                                    "crash_recoveries": 3, "successful_activations": 1,
                                    "synthetic_database_preserved": True}}
        result = run(task, sha, probe=probe, manager_probe=lab,
                     private_token=lambda: "secret")
        self.assertEqual(result["manager_lab"]["crash_recoveries"], 3)
        self.assertNotIn("secret", str(result))
        self.assertEqual(calls, ["secret"])
        calls.clear()
        run(task, sha, probe=lambda: {**probe(), "server_sha256": "0" * 64},
            manager_probe=lab, private_token=lambda: "secret")
        self.assertEqual(calls, [])
        with self.assertRaisesRegex(ValueError, "Version des tests"):
            read_task("pilot-010", get=lambda url: item({**candidate, "manifest_sha256": "0" * 64}),
                      now=2000000000)

    def test_manager_inventory_is_read_only_and_version_gated(self):
        candidate = {**TASK, "id": "pilot-011", "action": "manager_inventory"}
        task, sha = read_task("pilot-011", get=lambda url: item(candidate))
        probe = lambda: {"platform": "Darwin", "server_sha256": "a" * 64,
                         "app_present": True, "manager_present": True,
                         "git_available": True, "ollama_available": True}
        calls = []
        def inventory():
            calls.append(True)
            return {"schema": "rapbrain-manager-inventory-v1",
                    "applications_bundle": {"present": True},
                    "beta14_bundle": {"present": False}, "backup_state_present": True}
        result = run(task, sha, probe=probe, manager_inventory=inventory)
        self.assertEqual(result["manager_inventory"]["beta14_bundle"], {"present": False})
        self.assertEqual(len(calls), 1)
        run(task, sha, probe=lambda: {**probe(), "server_sha256": "0" * 64},
            manager_inventory=inventory)
        self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(ValueError, "Structure"):
            read_task("pilot-011", get=lambda url: item({**candidate, "path": "/"}))

    def test_watch_skips_existing_result(self):
        queue = item({"schema": "rapbrain-remote-queue-v1", "task_id": "pilot-001"})
        def fake(url, **kwargs):
            return queue if "queue/current.json" in url else {"type": "file"}
        self.assertEqual(watch_once("token", get=fake), ("pilot-001", "already_published"))

    def test_keychain_lookup_uses_fixed_service_and_no_shell(self):
        def fake(args, **kwargs):
            self.assertEqual(args[0], "/usr/bin/security")
            self.assertIn("com.gns.rapbrain.remote.p0", args)
            self.assertFalse(kwargs.get("shell", False))
            return type("Result", (), {"returncode": 0, "stdout": "github_pat_test\n"})()
        self.assertEqual(keychain_token(run_command=fake), "github_pat_test")


if __name__ == "__main__":
    unittest.main()
