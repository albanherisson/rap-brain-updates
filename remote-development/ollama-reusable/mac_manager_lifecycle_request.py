"""Stop or restart an installed, signed Rap Brain release via the Mac bridge."""

import http.client
from pathlib import Path
import re
import subprocess
import time

from mac_manager_install_request import request_lock, restart_foreign_server
from mac_manager_start_request import SERVER, manager_launch_context, start_server, verify_server
from mac_private_source_trial import github_file, keychain_token
from manager_remote_request import (
    REMOTE_REQUEST_SCHEMA, decode_remote_json, read_remote_json, remote_digest,
    remote_directory, validate_remote_request, write_remote_json,
)


ACTIONS = frozenset(("manager_stop", "manager_restart"))
SCHEMA = "rapbrain-manager-lifecycle-v1"
BUSY_REASONS = frozenset(("worker_busy_or_maintenance", "jobs_active_or_unknown_status"))
RECOVERY_SECONDS = 600


def parse_lifecycle_task(task, now=None):
    expected = {"schema", "id", "sequence", "action", "manifest_sha256", "expected_server_sha256",
                "release_commit", "authorization_commit", "expires_at"}
    if (type(task) is not dict or task.keys() != expected
            or task["schema"] != "rapbrain-remote-task-v6"
            or type(task["action"]) is not str or task["action"] not in ACTIONS
            or any(type(task[key]) is not str or not re.fullmatch(r"[a-f0-9]{40}", task[key])
                   for key in ("authorization_commit", "release_commit"))):
        raise ValueError("remote_manager_lifecycle_request_invalid")
    request = {key: value for key, value in task.items() if key != "authorization_commit"}
    request["schema"] = SCHEMA
    original = stop_request(request)
    validate_remote_request(original, now, allow_expired=True)
    current = time.time() if now is None else now
    if request["expires_at"] > current + 86400:
        raise ValueError("remote_manager_lifecycle_request_invalid")
    return request


def stop_request(request):
    return {
        "schema": REMOTE_REQUEST_SCHEMA, "id": request["id"], "sequence": request["sequence"],
        "manifest_sha256": request["manifest_sha256"], "expected_server_sha256": request["expected_server_sha256"],
        "expires_at": request["expires_at"],
    }


def authorize_lifecycle(task, request, *, fetch=github_file, token=keychain_token):
    path = "remote-development/manager-lifecycle-authorizations/" + task["id"] + ".json"
    if decode_remote_json(fetch(path, token(), task["authorization_commit"])) != request:
        raise ValueError("remote_manager_lifecycle_authorization_mismatch")


def advance_lifecycle_task(task, *, home=None, authorize=authorize_lifecycle, stop=restart_foreign_server,
                           launch_manager=manager_launch_context, start=start_server, now=time.time):
    request = parse_lifecycle_task(task)
    authorize(task, request)
    home = Path.home().resolve() if home is None else Path(home)
    directory = remote_directory(home, create=True)
    path = directory / ("lifecycle-" + request["id"] + ".json")
    digest = remote_digest(request)
    restart = request["action"] == "manager_restart"
    with request_lock(directory) as acquired:
        if not acquired:
            return {"state": "pending"}
        previous = read_remote_json(path)
        if previous is not None and (type(previous) is not dict or previous.get("request_sha256") != digest
                                     or previous.get("stop") not in ("stopped", "already_stopped")
                                     or previous.get("start") not in (None, "started", "already_running")):
            raise ValueError("remote_manager_lifecycle_receipt_mismatch")
        if previous is None:
            if now() >= request["expires_at"]:
                return {"state": "expired"}
            verify_server(home / SERVER, request["expected_server_sha256"])
            if restart:
                # Prove the route back before stopping the running server.
                launch_manager(home)
            try:
                stopped = stop(home, stop_request(request) | {"release_commit": request["release_commit"]},
                               installed=True)
            except ValueError as error:
                if str(error) in BUSY_REASONS:
                    return {"state": "pending"}
                raise
            if stopped not in ("stopped", "already_stopped"):
                raise ValueError("remote_manager_server_stop_unproven")
            previous = {"request_sha256": digest, "stop": stopped, "start": None}
            write_remote_json(path, previous)
        if not restart:
            return {"state": previous["stop"]}
        if previous["start"] is None:
            # A restart whose shutdown was already verified may finish during recovery.
            recovery = request["expires_at"] + RECOVERY_SECONDS
            if now() >= recovery:
                return {"state": "refused", "stop": previous["stop"], "reason": "remote_manager_restart_recovery_expired"}
            try:
                previous["start"] = start(home, request | {"expires_at": recovery})
            except (OSError, ValueError, http.client.HTTPException, subprocess.SubprocessError) as error:
                if str(error) in ("remote_manager_start_server_changed", "remote_manager_start_server_missing"):
                    return {"state": "refused", "stop": previous["stop"], "reason": str(error)}
                return {"state": "pending"}
            write_remote_json(path, previous)
        return {"state": "restarted" if previous["stop"] == "stopped" else "started",
                "stop": previous["stop"], "start": previous["start"], "manager_verified": True}
