import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import mac_decoder_track_status_request as track_status


class TrackStatusTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve()
        script = self.home / track_status.SERVER
        script.parent.mkdir(parents=True)
        script.write_bytes(b"track test server")
        self.task = {"schema": track_status.SCHEMA, "id": "track-test",
                     "action": "decoder_track_status", "expires_at": int(time.time()) + 300,
                     "expected_server_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                     "authorization_commit": "a" * 40}
        self.authorization = track_status.parse_track_task(self.task) | {
            "artist": "GNS", "title": "Private Song"}

    def test_exact_match_exposes_only_bounded_state(self):
        responses = {
            "/api/tracks?q=Private%20Song": [{"id": 7, "artist": "GNS", "title": "Private Song", "length": 1200}],
            "/api/jobs": [{"track_id": 7, "status": "running", "progress": 42, "error": "private error"}],
            "/api/decoder-reports": {"reports": [{"track_id": 7, "title": "Private Song",
                                                   "status": "done", "fragment": False, "blocked": ""}]},
        }
        http = Mock(side_effect=lambda port, method, path, **kw: json.dumps(responses[path]).encode())
        with patch.object(track_status, "server_ready", return_value=True):
            out = track_status.read_track(self.home, self.authorization, http=http)
        self.assertEqual(out["latest_progress"], 42)
        self.assertEqual(out["reports"], 1)
        self.assertEqual(out["ready_reports"], 1)
        self.assertTrue(out["has_lyrics"])
        self.assertNotIn("Private Song", json.dumps(out))
        self.assertNotIn("7", json.dumps(out))

    def test_private_authorization_must_include_exact_target(self):
        req = track_status.parse_track_task(self.task)
        fetch = lambda *args: json.dumps(self.authorization).encode()
        self.assertEqual(track_status.authorize_track(self.task, req, fetch=fetch, token=lambda: "private"),
                         self.authorization)
        bad = self.authorization | {"title": ""}
        with self.assertRaisesRegex(ValueError, "authorization_mismatch"):
            track_status.authorize_track(self.task, req, fetch=lambda *args: json.dumps(bad).encode(),
                                         token=lambda: "private")

    def test_ambiguous_match_is_not_disclosed(self):
        track = {"id": 7, "artist": "GNS", "title": "Private Song", "length": 10}
        responses = {"/api/tracks?q=Private%20Song": [track, track],
                     "/api/jobs": [], "/api/decoder-reports": {"reports": []}}
        http = Mock(side_effect=lambda port, method, path, **kw: json.dumps(responses[path]).encode())
        with patch.object(track_status, "server_ready", return_value=True):
            out = track_status.read_track(self.home, self.authorization, http=http)
        self.assertEqual(out, {"schema": "rapbrain-decoder-track-status-result-v1", "found": False})

    def test_old_and_partial_reports_are_distinguished_without_exposing_contents(self):
        responses = {
            "/api/tracks?q=Private%20Song": [{"id": 7, "artist": "GNS", "title": "Private Song", "length": 10}],
            "/api/jobs": [],
            "/api/decoder-reports": {"reports": [
                {"track_id": 7, "status": None, "fragment": False, "blocked": "", "body": "private"},
                {"track_id": 7, "status": "done", "fragment": True, "blocked": ""},
                {"track_id": 7, "status": "running", "fragment": False, "blocked": "active"},
            ]},
        }
        http = Mock(side_effect=lambda port, method, path, **kw: json.dumps(responses[path]).encode())
        with patch.object(track_status, "server_ready", return_value=True):
            out = track_status.read_track(self.home, self.authorization, http=http)
        self.assertEqual((out["reports"], out["ready_reports"], out["latest_job_state"]),
                         (3, 1, "not_recent"))
        self.assertNotIn("private", json.dumps(out))


if __name__ == "__main__":
    unittest.main()
