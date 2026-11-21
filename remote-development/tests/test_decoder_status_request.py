import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import mac_decoder_status_request as status


class DecoderStatusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.script = self.home / status.SERVER
        self.script.parent.mkdir(parents=True)
        self.script.write_bytes(b"test-server")
        self.task = {"schema": status.SCHEMA, "id": "status-test", "action": "decoder_status",
                     "expected_server_sha256": hashlib.sha256(b"test-server").hexdigest(),
                     "expires_at": int(time.time()) + 300, "authorization_commit": "a" * 40}

    def test_aggregate_response_discards_private_fields(self):
        replies = {
            "/api/stats": {"tracks": 9, "analyses": 7, "notes": 2, "artists": 3},
            "/api/jobs": [{"status": "running", "progress": 45, "title": "private song",
                            "error": "private error"}, {"status": "done", "progress": 100}],
            "/api/decoder-reports": {"reports": [{"title": "private report", "lyrics": "private lyrics"}]},
        }
        http = Mock(side_effect=lambda port, method, path, **kw: json.dumps(replies[path]).encode())
        with patch.object(status, "server_ready", return_value=True):
            output = status.read_status(self.home, status.parse_status_task(self.task), http=http)
        self.assertEqual(output["reports"], 1)
        self.assertEqual(output["latest_progress"], 45)
        self.assertEqual(output["recent_jobs"]["running"], 1)
        self.assertNotIn("private", json.dumps(output))
        self.assertEqual(http.call_count, 3)

    def test_private_authorization_must_match_exactly(self):
        request = status.parse_status_task(self.task)
        correct = json.dumps(request).encode()
        status.authorize_status(self.task, request, fetch=lambda *a: correct, token=lambda: "secret")
        with self.assertRaisesRegex(ValueError, "authorization_mismatch"):
            status.authorize_status(self.task, request, fetch=lambda *a: b'{}', token=lambda: "secret")

    def test_expired_task_and_server_mismatch_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "task_invalid"):
            status.parse_status_task(self.task, now=self.task["expires_at"])
        with patch.object(status, "server_ready", return_value=False):
            with self.assertRaisesRegex(ValueError, "server_unavailable"):
                status.read_status(self.home, status.parse_status_task(self.task), http=Mock())
        self.script.write_bytes(b"replaced")
        with self.assertRaisesRegex(ValueError, "server_changed"):
            status.read_status(self.home, status.parse_status_task(self.task), http=Mock())


if __name__ == "__main__":
    unittest.main()
