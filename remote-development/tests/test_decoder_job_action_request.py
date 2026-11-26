import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import mac_decoder_job_action_request as actions


class DecoderJobActionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        script = self.home / actions.SERVER
        script.parent.mkdir(parents=True)
        script.write_bytes(b"reviewed server")
        (self.home / actions.STATE_DIR).mkdir(parents=True)
        self.task = {"schema": actions.SCHEMA, "id": "one-job", "action": "decoder_cancel",
                     "expected_server_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                     "expires_at": int(time.time()) + 300, "authorization_commit": "a" * 40}
        self.auth = actions.parse_action_task(self.task) | {"artist": "GNS", "title": "Private Song"}
        self.tracks = [{"id": 7, "artist": "GNS", "title": "Private Song"}]

    def http(self, state):
        return Mock(side_effect=lambda port, method, path, **kw: json.dumps(
            self.tracks if path.startswith("/api/tracks?") else
            [{"id": 11, "track_id": 7, "status": state}]).encode())

    def test_cancel_once_and_replay_does_not_post(self):
        post = Mock(return_value={"ok": True})
        with patch.object(actions, "server_ready", return_value=True):
            first = actions.act_on_job(self.home, self.auth, http=self.http("running"), post=post)
            second = actions.act_on_job(self.home, self.auth, http=self.http("running"), post=post)
        self.assertEqual(first, {"state": "cancel_requested", "replayed": False})
        self.assertEqual(second, {"state": "cancel_requested", "replayed": True})
        post.assert_called_once_with(11, "cancel")
        self.assertNotIn("Private Song", json.dumps(first))

    def test_retry_only_cancelled_job_and_keep_same_job_id(self):
        auth = self.auth | {"action": "decoder_retry"}
        post = Mock(return_value={"ok": True})
        with patch.object(actions, "server_ready", return_value=True):
            result = actions.act_on_job(self.home, auth, http=self.http("cancelled"), post=post)
        self.assertEqual(result["state"], "retry_requested")
        post.assert_called_once_with(11, "retry")

    def test_refuse_wrong_state_and_ambiguous_match(self):
        post = Mock(return_value={"ok": True})
        with patch.object(actions, "server_ready", return_value=True):
            result = actions.act_on_job(self.home, self.auth, http=self.http("cancelled"), post=post)
            self.tracks *= 2
            result2 = actions.act_on_job(self.home, self.auth, http=self.http("running"), post=post)
        self.assertEqual(result["state"], "not_eligible")
        self.assertEqual(result2["state"], "not_eligible")
        post.assert_not_called()

    def test_lost_reply_cannot_retry_side_effect(self):
        post = Mock(side_effect=TimeoutError("lost reply"))
        with patch.object(actions, "server_ready", return_value=True):
            with self.assertRaises(TimeoutError):
                actions.act_on_job(self.home, self.auth, http=self.http("running"), post=post)
            second = actions.act_on_job(self.home, self.auth, http=self.http("running"), post=post)
        self.assertEqual(second["state"], "uncertain")
        post.assert_called_once()

    def test_private_authorization_exact(self):
        request = actions.parse_action_task(self.task)
        auth = actions.authorize_action(self.task, request,
            fetch=lambda *args: json.dumps(self.auth).encode(), token=lambda: "private")
        self.assertEqual(auth, self.auth)
        with self.assertRaisesRegex(ValueError, "authorization_mismatch"):
            actions.authorize_action(self.task, request,
                fetch=lambda *args: json.dumps(self.auth | {"action": "decoder_retry"}).encode(),
                token=lambda: "private")


if __name__ == "__main__":
    unittest.main()
