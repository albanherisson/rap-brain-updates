"""Queue one privately selected Decoder track with a durable no-repeat receipt."""

import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
from urllib.parse import quote

from mac_decoder_track_status_request import parse_track_task
from mac_manager_start_request import SERVER, local_request, server_ready, verify_server
from mac_private_source_trial import github_file, keychain_token
from manager_remote_request import decode_remote_json


SCHEMA = "rapbrain-remote-task-v10"
STATE_DIR = Path("Library/Application Support/RapBrainRemoteBridge")


def parse_queue_task(task, now=None):
    if (type(task) is not dict or task.get("schema") != SCHEMA or task.get("action") != "decoder_queue"):
        raise ValueError("remote_decoder_queue_task_invalid")
    adapted = task | {"schema": "rapbrain-remote-task-v9", "action": "decoder_track_status"}
    request = parse_track_task(adapted, now=now)
    return request | {"schema": "rapbrain-decoder-queue-v1"}


def authorize_queue(task, request, fetch=github_file, token=keychain_token):
    path = "remote-development/decoder-queue-authorizations/" + request["id"] + ".json"
    authorization = decode_remote_json(fetch(path, token(), task["authorization_commit"]))
    if (type(authorization) is not dict or authorization.keys() != request.keys() | {"artist", "title"}
            or any(authorization.get(key) != value for key, value in request.items())
            or any(type(authorization[key]) is not str or not authorization[key].strip()
                   or len(authorization[key]) > limit for key, limit in (("artist", 120), ("title", 180)))):
        raise ValueError("remote_decoder_queue_authorization_mismatch")
    return authorization


def journal_path(home, task_id):
    return home / STATE_DIR / ("decoder-queue-" + task_id + ".json")


def journal_read(path):
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        raise ValueError("remote_decoder_queue_journal_unsafe")
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size > 512):
        raise ValueError("remote_decoder_queue_journal_unsafe")
    return decode_remote_json(path.read_bytes())


def journal_write(path, record):
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    fd, temporary = tempfile.mkstemp(prefix=".decoder-queue-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def post_queue(track_id):
    body = json.dumps({"ids": [track_id]}).encode()
    connection = http.client.HTTPConnection("127.0.0.1", 8765, timeout=5)
    try:
        connection.request("POST", "/api/queue-album", body=body,
                           headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
        response = connection.getresponse()
        raw = response.read(4097)
        if response.status != 200 or len(raw) > 4096:
            raise ValueError("remote_decoder_queue_http_refused")
        return decode_remote_json(raw)
    finally:
        connection.close()


def queue_track(home, authorization, *, call=subprocess.run, http=local_request, post=post_queue):
    script = home / SERVER
    verify_server(script, authorization["expected_server_sha256"])
    if not server_ready(script, call, http) or time.time() >= authorization["expires_at"]:
        raise ValueError("remote_decoder_queue_server_unavailable")
    directory = home / STATE_DIR
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("remote_decoder_queue_state_unsafe")
    lock_path = directory / "decoder-queue.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("remote_decoder_queue_lock_unsafe")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = journal_path(home, authorization["id"])
        identity = hashlib.sha256(json.dumps(authorization, sort_keys=True).encode()).hexdigest()
        previous = journal_read(path)
        if previous is not None:
            if type(previous) is not dict or previous.get("identity") != identity:
                raise ValueError("remote_decoder_queue_journal_mismatch")
            if previous.get("state") == "queued":
                return {"state": "queued", "queued": True, "replayed": True}
            if previous.get("state") == "already_active":
                return {"state": "already_active", "queued": False, "replayed": True}
            return {"state": "uncertain", "queued": False, "replayed": True}
        query = quote(authorization["title"], safe="")
        tracks = json.loads(http(8765, "GET", "/api/tracks?q=" + query, limit=131072))
        if type(tracks) is not list or len(tracks) > 500:
            raise ValueError("remote_decoder_queue_tracks_invalid")
        matches = [t for t in tracks if type(t) is dict
                   and str(t.get("artist", "")).casefold() == authorization["artist"].casefold()
                   and str(t.get("title", "")).casefold() == authorization["title"].casefold()]
        if (len(matches) != 1 or type(matches[0].get("id")) is not int
                or type(matches[0].get("length")) is not int or matches[0]["length"] <= 0):
            return {"state": "not_eligible", "queued": False}
        track_id = matches[0]["id"]
        if not server_ready(script, call, http) or time.time() >= authorization["expires_at"]:
            raise ValueError("remote_decoder_queue_server_changed")
        # The prepared receipt is durable before the side-effect. After a crash,
        # an uncertain receipt refuses to send the same request a second time.
        journal_write(path, {"identity": identity, "state": "prepared"})
        response = post(track_id)
        if type(response) is not dict or response.get("ok") is not True or type(response.get("queued")) is not int:
            return {"state": "uncertain", "queued": False}
        if response["queued"] not in (0, 1):
            return {"state": "uncertain", "queued": False}
        state = "queued" if response["queued"] == 1 else "already_active"
        journal_write(path, {"identity": identity, "state": state})
        return {"state": state, "queued": response["queued"] == 1, "replayed": False}
    finally:
        os.close(fd)


def advance_queue_task(task, *, home=None, authorize=authorize_queue, queue=queue_track):
    request = parse_queue_task(task)
    auth = authorize(task, request)
    return queue(Path.home().resolve() if home is None else home, auth)
