import base64
import json
import unittest

from mac_bridge import contents_url, read_queue, read_task, run, publish, watch_once


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

    def test_watch_skips_existing_result(self):
        queue = item({"schema": "rapbrain-remote-queue-v1", "task_id": "pilot-001"})
        def fake(url, **kwargs):
            return queue if "queue/current.json" in url else {"type": "file"}
        self.assertEqual(watch_once("token", get=fake), ("pilot-001", "already_published"))


if __name__ == "__main__":
    unittest.main()
