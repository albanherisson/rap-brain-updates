"""Cancel or retry the latest verified track job, once per private authorization."""

import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import stat
import subprocess
import time
from urllib.parse import quote

from mac_decoder_queue_request import STATE_DIR, journal_read, journal_write
from mac_decoder_track_status_request import parse_track_task
from mac_manager_start_request import SERVER, local_request, server_ready, verify_server
from mac_private_source_trial import github_file, keychain_token
from manager_remote_request import decode_remote_json


SCHEMA = "rapbrain-remote-task-v11"
ACTIONS = {"decoder_cancel": ("running", "pending"), "decoder_retry": ("cancelled", "interrupted", "error")}


def parse_action_task(task, now=None):
    if type(task) is not dict or task.get("schema") != SCHEMA or task.get("action") not in ACTIONS:
        raise ValueError("remote_decoder_job_action_invalid")
    adapted = task | {"schema": "rapbrain-remote-task-v9", "action": "decoder_track_status"}
    request = parse_track_task(adapted, now=now)
    return request | {"schema": "rapbrain-decoder-job-action-v1", "action": task["action"]}


def authorize_action(task, request, fetch=github_file, token=keychain_token):
    path = "remote-development/decoder-job-action-authorizations/" + request["id"] + ".json"
    authorization = decode_remote_json(fetch(path, token(), task["authorization_commit"]))
    if (type(authorization) is not dict or authorization.keys() != request.keys() | {"artist", "title"}
            or any(authorization.get(key) != value for key, value in request.items())
            or any(type(authorization[key]) is not str or not authorization[key].strip()
                   or len(authorization[key]) > limit for key, limit in (("artist", 120), ("title", 180)))):
        raise ValueError("remote_decoder_job_authorization_mismatch")
    return authorization


def post_action(job_id, action):
    body = json.dumps({"id": job_id, "action": action}).encode()
    connection = http.client.HTTPConnection("127.0.0.1", 8765, timeout=5)
    try:
        connection.request("POST", "/api/job-action", body=body,
                           headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
        response = connection.getresponse()
        raw = response.read(4097)
        if response.status != 200 or len(raw) > 4096:
            raise ValueError("remote_decoder_job_http_refused")
        return decode_remote_json(raw)
    finally:
        connection.close()


def act_on_job(home, authorization, *, call=subprocess.run, http=local_request, post=post_action):
    script = home / SERVER
    verify_server(script, authorization["expected_server_sha256"])
    if not server_ready(script, call, http) or time.time() >= authorization["expires_at"]:
        raise ValueError("remote_decoder_job_server_unavailable")
    directory = home / STATE_DIR
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("remote_decoder_job_state_unsafe")
    lock_path = directory / "decoder-queue.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("remote_decoder_job_lock_unsafe")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = directory / ("decoder-job-action-" + authorization["id"] + ".json")
        identity = hashlib.sha256(json.dumps(authorization, sort_keys=True).encode()).hexdigest()
        previous = journal_read(path)
        if previous is not None:
            if type(previous) is not dict or previous.get("identity") != identity:
                raise ValueError("remote_decoder_job_receipt_mismatch")
            if previous.get("state") in ("cancel_requested", "retry_requested"):
                return {"state": previous["state"], "replayed": True}
            return {"state": "uncertain", "replayed": True}
        tracks = json.loads(http(8765, "GET", "/api/tracks?q=" + quote(authorization["title"], safe=""),
                                 limit=131072))
        jobs = json.loads(http(8765, "GET", "/api/jobs", limit=131072))
        if type(tracks) is not list or len(tracks) > 500 or type(jobs) is not list or len(jobs) > 100:
            raise ValueError("remote_decoder_job_response_invalid")
        matches = [t for t in tracks if type(t) is dict
                   and str(t.get("artist", "")).casefold() == authorization["artist"].casefold()
                   and str(t.get("title", "")).casefold() == authorization["title"].casefold()]
        if len(matches) != 1 or type(matches[0].get("id")) is not int:
            return {"state": "not_eligible", "replayed": False}
        related = [j for j in jobs if type(j) is dict and j.get("track_id") == matches[0]["id"]]
        if not related or type(related[0].get("id")) is not int:
            return {"state": "not_eligible", "replayed": False}
        job = related[0]  # /api/jobs returns descending job IDs.
        expected = ACTIONS[authorization["action"]]
        if job.get("status") not in expected or sum(j.get("status") in expected for j in related) != 1:
            return {"state": "not_eligible", "replayed": False}
        if not server_ready(script, call, http) or time.time() >= authorization["expires_at"]:
            raise ValueError("remote_decoder_job_server_changed")
        # A lost response can never result in a second POST for this authorization.
        journal_write(path, {"identity": identity, "state": "prepared"})
        result = post(job["id"], "cancel" if authorization["action"] == "decoder_cancel" else "retry")
        if type(result) is not dict or result.get("ok") is not True:
            return {"state": "uncertain", "replayed": False}
        state = "cancel_requested" if authorization["action"] == "decoder_cancel" else "retry_requested"
        journal_write(path, {"identity": identity, "state": state})
        return {"state": state, "replayed": False}
    finally:
        os.close(fd)


def advance_action_task(task, *, home=None, authorize=authorize_action, act=act_on_job):
    request = parse_action_task(task)
    authorization = authorize(task, request)
    return act(Path.home().resolve() if home is None else home, authorization)
