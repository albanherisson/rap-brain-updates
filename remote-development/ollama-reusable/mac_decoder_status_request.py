"""Read bounded, aggregate Decoder status from the verified local Rap Brain server."""

import http.client
import json
from pathlib import Path
import re
import subprocess
import time

from mac_manager_start_request import SERVER, local_request, server_ready, verify_server
from mac_private_source_trial import github_file, keychain_token
from manager_remote_request import decode_remote_json


SCHEMA = "rapbrain-remote-task-v8"
FIELDS = {"schema", "id", "action", "expected_server_sha256", "expires_at", "authorization_commit"}


def parse_status_task(task, now=None):
    current = time.time() if now is None else now
    if (type(task) is not dict or task.keys() != FIELDS or task["schema"] != SCHEMA
            or task["action"] != "decoder_status" or type(task["id"]) is not str
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", task["id"])
            or type(task["expected_server_sha256"]) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", task["expected_server_sha256"])
            or type(task["authorization_commit"]) is not str
            or not re.fullmatch(r"[a-f0-9]{40}", task["authorization_commit"])
            or type(task["expires_at"]) is not int
            or not current < task["expires_at"] <= current + 86400):
        raise ValueError("remote_decoder_status_task_invalid")
    return {"schema": "rapbrain-decoder-status-v1", "id": task["id"],
            "expected_server_sha256": task["expected_server_sha256"],
            "expires_at": task["expires_at"]}


def authorize_status(task, request, fetch=github_file, token=keychain_token):
    path = "remote-development/decoder-status-authorizations/" + request["id"] + ".json"
    if decode_remote_json(fetch(path, token(), task["authorization_commit"])) != request:
        raise ValueError("remote_decoder_status_authorization_mismatch")


def read_status(home, request, *, call=subprocess.run, http=local_request):
    script = home / SERVER
    verify_server(script, request["expected_server_sha256"])
    if not server_ready(script, call, http):
        raise ValueError("remote_decoder_status_server_unavailable")
    if time.time() >= request["expires_at"]:
        raise ValueError("remote_decoder_status_task_expired")
    try:
        stats = json.loads(http(8765, "GET", "/api/stats", limit=4096))
        jobs = json.loads(http(8765, "GET", "/api/jobs", limit=131072))
        catalog = json.loads(http(8765, "GET", "/api/decoder-reports", limit=2097152))
    except (UnicodeError, json.JSONDecodeError, http.client.HTTPException):
        raise ValueError("remote_decoder_status_response_invalid") from None
    if (type(stats) is not dict or any(type(stats.get(k)) is not int or stats[k] < 0
            for k in ("tracks", "analyses", "notes", "artists"))
            or type(jobs) is not list or len(jobs) > 100
            or type(catalog) is not dict or type(catalog.get("reports")) is not list
            or len(catalog["reports"]) > 10000):
        raise ValueError("remote_decoder_status_response_invalid")
    counts = {k: 0 for k in ("pending", "running", "done", "failed", "other")}
    latest_progress = None
    for job in jobs:
        if type(job) is not dict or type(job.get("status")) is not str:
            raise ValueError("remote_decoder_status_response_invalid")
        state = job["status"] if job["status"] in counts else "other"
        counts[state] += 1
        if latest_progress is None:
            progress = job.get("progress")
            if type(progress) is int and 0 <= progress <= 100:
                latest_progress = progress
    # All titles, lyrics, report bodies, errors and local paths stay on the Mac.
    if not server_ready(script, call, http):
        raise ValueError("remote_decoder_status_server_changed")
    return {"schema": "rapbrain-decoder-status-result-v1", "tracks": stats["tracks"],
            "analyses": stats["analyses"], "reports": len(catalog["reports"]),
            "recent_jobs": counts, "latest_progress": latest_progress,
            "server_verified": True}


def advance_status_task(task, *, home=None, authorize=authorize_status, read=read_status):
    request = parse_status_task(task)
    authorize(task, request)
    return read(Path.home().resolve() if home is None else home, request)
