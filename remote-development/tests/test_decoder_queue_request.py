import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import mac_decoder_queue_request as queue


class DecoderQueueTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve()
        script = self.home / queue.SERVER
        script.parent.mkdir(parents=True)
        script.write_bytes(b"queue test server")
        (self.home / queue.STATE_DIR).mkdir(parents=True)
        self.task = {"schema": queue.SCHEMA, "id": "queue-test", "action": "decoder_queue",
                     "expected_server_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                     "expires_at": int(time.time()) + 300, "authorization_commit": "a" * 40}
        self.auth = queue.parse_queue_task(self.task) | {"artist": "GNS", "title": "Private Song"}
        tracks = [{"id": 7, "artist": "GNS", "title": "Private Song", "length": 123}]
        self.http = Mock(return_value=json.dumps(tracks).encode())

    def test_one_side_effect_and_durable_replay(self):
        post = Mock(return_value={"ok": True, "queued": 1})
        with patch.object(queue, "server_ready", return_value=True):
            first = queue.queue_track(self.home, self.auth, http=self.http, post=post)
            second = queue.queue_track(self.home, self.auth, http=self.http, post=post)
        self.assertEqual(first, {"state": "queued", "queued": True, "replayed": False})
        self.assertEqual(second, {"state": "queued", "queued": True, "replayed": True})
        post.assert_called_once_with(7)
        self.assertEqual(self.http.call_count, 1)
        self.assertNotIn("Private Song", json.dumps(first))

    def test_uncertain_response_never_retries_post(self):
        post = Mock(side_effect=TimeoutError("reply lost"))
        with patch.object(queue, "server_ready", return_value=True):
            with self.assertRaises(TimeoutError):
                queue.queue_track(self.home, self.auth, http=self.http, post=post)
            result = queue.queue_track(self.home, self.auth, http=self.http, post=post)
        self.assertEqual(result["state"], "uncertain")
        post.assert_called_once()

    def test_private_target_required(self):
        request = queue.parse_queue_task(self.task)
        self.assertEqual(queue.authorize_queue(self.task, request,
                         fetch=lambda *args: json.dumps(self.auth).encode(), token=lambda: "private"), self.auth)
        with self.assertRaisesRegex(ValueError, "authorization_mismatch"):
            queue.authorize_queue(self.task, request, fetch=lambda *args: b'{}', token=lambda: "private")


if __name__ == "__main__":
    unittest.main()
