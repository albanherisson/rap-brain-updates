"""Read one named track's Decoder state without publishing its identity."""

import http.client
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import quote

from mac_manager_start_request import SERVER, local_request, server_ready, verify_server
from mac_private_source_trial import github_file, keychain_token
from manager_remote_request import decode_remote_json


SCHEMA = "rapbrain-remote-task-v9"
FIELDS = {"schema", "id", "action", "expected_server_sha256", "expires_at", "authorization_commit"}


def parse_track_task(task, now=None):
    current = time.time() if now is None else now
    if (type(task) is not dict or task.keys() != FIELDS or task["schema"] != SCHEMA
            or task["action"] != "decoder_track_status" or type(task["id"]) is not str
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", task["id"])
            or type(task["expected_server_sha256"]) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", task["expected_server_sha256"])
            or type(task["authorization_commit"]) is not str
            or not re.fullmatch(r"[a-f0-9]{40}", task["authorization_commit"])
            or type(task["expires_at"]) is not int
            or not current < task["expires_at"] <= current + 86400):
        raise ValueError("remote_decoder_track_task_invalid")
    return {"schema": "rapbrain-decoder-track-status-v1", "id": task["id"],
            "expected_server_sha256": task["expected_server_sha256"],
            "expires_at": task["expires_at"]}


def authorize_track(task, request, fetch=github_file, token=keychain_token):
    path = "remote-development/decoder-track-authorizations/" + request["id"] + ".json"
    authorization = decode_remote_json(fetch(path, token(), task["authorization_commit"]))
    if (type(authorization) is not dict or authorization.keys() != request.keys() | {"artist", "title"}
            or any(authorization.get(key) != value for key, value in request.items())
            or any(type(authorization[key]) is not str or not authorization[key].strip()
                   or len(authorization[key]) > limit for key, limit in (("artist", 120), ("title", 180)))):
        raise ValueError("remote_decoder_track_authorization_mismatch")
    return authorization


def read_track(home, authorization, *, call=subprocess.run, http=local_request):
    script = home / SERVER
    verify_server(script, authorization["expected_server_sha256"])
    if not server_ready(script, call, http) or time.time() >= authorization["expires_at"]:
        raise ValueError("remote_decoder_track_server_unavailable")
    try:
        query = quote(authorization["title"], safe="")
        tracks = json.loads(http(8765, "GET", "/api/tracks?q=" + query, limit=131072))
        jobs = json.loads(http(8765, "GET", "/api/jobs", limit=131072))
        catalog = json.loads(http(8765, "GET", "/api/decoder-reports", limit=2097152))
    except (UnicodeError, json.JSONDecodeError, http.client.HTTPException):
        raise ValueError("remote_decoder_track_response_invalid") from None
    if (type(tracks) is not list or len(tracks) > 500 or type(jobs) is not list or len(jobs) > 100
            or type(catalog) is not dict or type(catalog.get("reports")) is not list):
        raise ValueError("remote_decoder_track_response_invalid")
    matches = [t for t in tracks if type(t) is dict
               and str(t.get("artist", "")).casefold() == authorization["artist"].casefold()
               and str(t.get("title", "")).casefold() == authorization["title"].casefold()]
    if len(matches) != 1 or type(matches[0].get("id")) is not int:
        return {"schema": "rapbrain-decoder-track-status-result-v1", "found": False}
    track = matches[0]
    track_id = track["id"]
    related_jobs = [j for j in jobs if type(j) is dict and j.get("track_id") == track_id]
    related_reports = [r for r in catalog["reports"] if type(r) is dict and r.get("track_id") == track_id]
    latest = related_jobs[0] if related_jobs else {}
    progress = latest.get("progress")
    if type(progress) is not int or not 0 <= progress <= 100:
        progress = None
    state = ("not_recent" if not related_jobs else
             latest.get("status") if latest.get("status") in
             ("pending", "running", "done", "error", "failed", "interrupted", "cancelled") else "other")
    ready_reports = sum(1 for report in related_reports
                        if not report.get("fragment") and not report.get("blocked")
                        and report.get("status") in (None, "done"))
    if not server_ready(script, call, http):
        raise ValueError("remote_decoder_track_server_changed")
    # No track ID, artist, title, lyrics, report body or job error leaves the Mac.
    return {"schema": "rapbrain-decoder-track-status-result-v1", "found": True,
            "has_lyrics": type(track.get("length")) is int and track["length"] > 0,
            "reports": len(related_reports), "ready_reports": ready_reports,
            "latest_job_state": state,
            "latest_progress": progress, "server_verified": True}


def advance_track_task(task, *, home=None, authorize=authorize_track, read=read_track):
    request = parse_track_task(task)
    auth = authorize(task, request)
    return read(Path.home().resolve() if home is None else home, auth)
