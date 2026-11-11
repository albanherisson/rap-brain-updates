"""Authorize one release via the private repo and hand it to the installed Manager."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

from mac_private_source_trial import github_file, keychain_token
from manager_remote_request import (REMOTE_FIELDS, REMOTE_REQUEST_SCHEMA, REMOTE_TERMINAL,
                                    decode_remote_json, lock_remote_directory, queue_remote_request,
                                    read_remote_json, remote_directory, remote_receipt,
                                    save_remote_receipt, validate_remote_request)


APP = Path("Downloads/RapBrainManager_App_Beta14/Rap Brain Manager Beta 14.app")
LAUNCHER = Path("Contents/Resources/launch_manager.py")
LAUNCHER_SHA = "ceda87b7655d643ca6e9dc66afa0f5d3e0d20857abd2e8c202b8a1978b86a660"
HANDOFF_RECEIPT = Path("Downloads/RapBrainManagerBackups/secure-update/manager-handoff-result.json")
RESTART_SERVER_SHA = "4cdab9087a33855e79e8fee5d639cae3489fc7a4399cdc6e0099b15ad8a7e16c"
RESTART_URL = ("https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
               "708bdc4035dd46a85934a12989fb6ec2ed25741f/remote-development/mac_prepare_manager_restart.py")
RESTART_SHA = "3f1e530d84a821e0105e7c4c3ad3b99f52c6fcec986ef50ec8441e3c8cedf040"


def parse_install_task(task, now=None):
    expected = REMOTE_FIELDS | {"action", "authorization_commit"}
    if (type(task) is not dict or task.keys() != expected
            or task["schema"] != "rapbrain-remote-task-v3" or task["action"] != "manager_install"
            or type(task["authorization_commit"]) is not str
            or not re.fullmatch(r"[0-9a-f]{40}", task["authorization_commit"])):
        raise ValueError("invalid_remote_manager_task")
    request = {key: task[key] for key in REMOTE_FIELDS}
    request["schema"] = REMOTE_REQUEST_SCHEMA
    return validate_remote_request(request, now, allow_expired=True)


def authorize_install_task(task, request, *, token=keychain_token, fetch=github_file):
    path = "remote-development/manager-authorizations/" + request["id"] + ".json"
    authorization = decode_remote_json(fetch(path, token(), task["authorization_commit"]))
    if authorization != request:
        raise ValueError("remote_manager_private_authorization_mismatch")


def open_manager(app, call=subprocess.run):
    if app.resolve() != app or not app.is_dir():
        return False
    signature = call(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                     capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    if signature.returncode != 0:
        return False
    return call(["/usr/bin/open", "-g", str(app)], capture_output=True,
                stdin=subprocess.DEVNULL, timeout=15).returncode == 0


def restart_foreign_server(home, request, opener=urllib.request.urlopen, call=subprocess.run):
    if request["expected_server_sha256"] != RESTART_SERVER_SHA:
        raise ValueError("remote_manager_restart_baseline_unreviewed")
    with tempfile.TemporaryDirectory(prefix="rapbrain-authorized-server-restart-") as temporary:
        root = Path(temporary).resolve()
        with opener(RESTART_URL, timeout=20) as response:
            raw = response.read(50_001)
            if (response.geturl() != RESTART_URL or len(raw) > 50_000
                    or hashlib.sha256(raw).hexdigest() != RESTART_SHA):
                raise ValueError("remote_manager_restart_code_mismatch")
        script = root / "restart.py"
        script.write_bytes(raw)
        env = {"HOME": str(home), "TMPDIR": str(root), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        result = call([sys.executable, "-I", "-B", str(script)], cwd=root, env=env,
                      capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
        if result.returncode != 0:
            try:
                proof = decode_remote_json(result.stderr.splitlines()[-1])
                reason = proof.get("reason", "")
            except (IndexError, AttributeError, ValueError):
                reason = ""
            if isinstance(reason, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,80}", reason):
                raise ValueError(reason)
            raise ValueError("remote_manager_server_stop_refused")
        try:
            proof = decode_remote_json(result.stdout.splitlines()[-1])
        except (IndexError, ValueError):
            raise ValueError("remote_manager_server_stop_unproven") from None
        if proof not in ({"status": "pass", "server": "stopped"},
                         {"status": "pass", "server": "already_stopped"}):
            raise ValueError("remote_manager_server_stop_unproven")


def install_receipt(home, record):
    path = home / HANDOFF_RECEIPT
    if path.parent.resolve() != path.parent:
        raise ValueError("unsafe_remote_manager_handoff_receipt")
    receipt = read_remote_json(path)
    if (type(receipt) is not dict or receipt.get("attempt") != record.get("attempt")
            or receipt.get("state") not in REMOTE_TERMINAL):
        return None
    return receipt["state"]


def advance_install_task(task, *, home=None, authorize=authorize_install_task,
                         opener=open_manager, restart=restart_foreign_server):
    home = Path.home().resolve() if home is None else Path(home)
    request = parse_install_task(task)
    authorize(task, request)
    directory = remote_directory(home, create=True)
    try:
        fd = lock_remote_directory(directory)
    except BlockingIOError:
        return {"state": "pending"}
    try:
        record = remote_receipt(directory, request)
        stage = record["state"] if record else None
        if stage in REMOTE_TERMINAL:
            return {key: record[key] for key in ("state", "reason", "manager_reopened")
                    if key in record}
        if stage == "handoff":
            finished = install_receipt(home, record)
            if finished is None:
                return {"state": "pending"} if time.time() < request["expires_at"] else {"state": "check_required"}
            reopened = False
            if finished in ("committed", "rolled_back"):
                try:
                    reopened = opener(home / APP)
                except (OSError, subprocess.SubprocessError):
                    pass
            save_remote_receipt(directory, request, finished, attempt=record["attempt"], manager_reopened=reopened)
            return {"state": finished, "manager_reopened": reopened}
        if stage == "dispatching":
            return {"state": "pending"} if time.time() < request["expires_at"] else {"state": "check_required"}
        if time.time() >= request["expires_at"]:
            save_remote_receipt(directory, request, "expired")
            return {"state": "expired"}
        if stage == "waiting_foreign_server":
            try:
                restart(home, request)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                record = save_remote_receipt(directory, request, "refused", reason=str(exc))
                return {"state": "refused", "reason": record.get("reason", "server_stop_refused")}
            save_remote_receipt(directory, request, "server_released")
            return {"state": "pending"}
        if stage is not None:
            return {"state": "pending"}
        app = home / APP
        launcher = app / LAUNCHER
        if (launcher.resolve() != launcher or not launcher.is_file()
                or hashlib.sha256(launcher.read_bytes()).hexdigest() != LAUNCHER_SHA):
            return {"state": "refused", "reason": "remote_manager_launcher_upgrade_required"}
        queue_remote_request(directory, request)
        try:
            opened = opener(app)
        except (OSError, subprocess.SubprocessError):
            opened = False
        if not opened:
            save_remote_receipt(directory, request, "refused", reason="remote_manager_open_refused")
            return {"state": "refused", "reason": "remote_manager_open_refused"}
        return {"state": "pending"}
    finally:
        os.close(fd)
