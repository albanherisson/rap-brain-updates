"""Open the reviewed Rap Brain server through the Manager's local launch API."""

import hashlib
import http.client
import os
from pathlib import Path
import re
import subprocess
import time

from mac_manager_install_request import (
    APP, LAUNCHER, compatible_launcher, dashboard_record, open_manager,
    runtime_directories, wait_for_manager,
)
from mac_private_source_trial import github_file, keychain_token
from manager_remote_request import decode_remote_json


FIELDS = {"schema", "id", "action", "expected_server_sha256", "expires_at", "authorization_commit"}
START_TOKEN = re.compile(rb"\bLAUNCH_TOKEN='([A-Za-z0-9_-]{30,80})'")
SERVER = Path("Downloads/rap-brain/server.py")


def parse_start_task(task, now=None):
    current = time.time() if now is None else now
    if (type(task) is not dict or task.keys() != FIELDS
            or task["schema"] != "rapbrain-remote-task-v5" or task["action"] != "manager_start"
            or not isinstance(task["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", task["id"])
            or not isinstance(task["authorization_commit"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", task["authorization_commit"])
            or not isinstance(task["expected_server_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", task["expected_server_sha256"])
            or type(task["expires_at"]) is not int or not current < task["expires_at"] <= current + 86400):
        raise ValueError("remote_manager_start_request_invalid")
    return {"schema": "rapbrain-manager-start-v1", "id": task["id"],
            "expected_server_sha256": task["expected_server_sha256"], "expires_at": task["expires_at"]}


def authorize_start(task, request, fetch=github_file, token=keychain_token):
    path = "remote-development/manager-start-authorizations/" + request["id"] + ".json"
    if decode_remote_json(fetch(path, token(), task["authorization_commit"])) != request:
        raise ValueError("remote_manager_start_authorization_mismatch")


def verify_server(script, expected):
    if script.resolve() != script or not script.is_file():
        raise ValueError("remote_manager_start_server_missing")
    with script.open("rb") as stream:
        raw = stream.read(250_001)
    if not 0 < len(raw) <= 250_000 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("remote_manager_start_server_changed")


def process_output(args, call):
    result = call(args, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=4)
    return result.stdout.strip() if result.returncode == 0 and not result.stderr else ""


def listener_pid(port, call):
    output = process_output(["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"], call)
    lines = output.splitlines()
    pids = [int(line[1:]) for line in lines if re.fullmatch(r"p[1-9][0-9]*", line)]
    if len(pids) == 1 and all(re.fullmatch(r"(?:p[1-9][0-9]*|f[0-9]+[a-zA-Z]?)", line) for line in lines):
        return pids[0]
    return None


def owns_process(pid, launcher, call, *, server=False):
    if pid is None:
        return False
    output = process_output(["/bin/ps", "-ww", "-p", str(pid), "-o", "uid=,command="], call)
    fields = output.split(None, 1)
    if len(fields) != 2 or fields[0] != str(os.getuid()):
        return False
    flags = " -u " if server else " "
    suffix = "" if server else r"(?: --no-browser)?"
    pattern = r"[^\n]*[Pp]ython[0-9.]*" + flags + re.escape(str(launcher)) + suffix
    return re.fullmatch(pattern, fields[1].strip()) is not None


def dashboard_endpoint(home, call):
    for runtime in runtime_directories(call):
        record = dashboard_record(runtime)
        if record is None or listener_pid(record["port"], call) != record["pid"]:
            continue
        parent = process_output(["/bin/ps", "-p", str(record["pid"]), "-o", "ppid="], call)
        if parent.isdecimal() and owns_process(int(parent), home / APP / LAUNCHER, call):
            return runtime, record
    return None


def local_request(port, method, path, *, headers=None, limit=4096):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        raw = response.read(limit+1)
        if response.status != 200 or len(raw) > limit:
            raise ValueError("remote_manager_start_http_refused")
        return raw
    finally:
        connection.close()


def server_ready(script, call, request):
    pid = listener_pid(8765, call)
    if not owns_process(pid, script, call, server=True):
        return False
    try:
        reply = decode_remote_json(request(8765, "GET", "/api/health"))
        return reply == {"ok": True, "worker": "separate_process"} and listener_pid(8765, call) == pid
    except (OSError, ValueError, http.client.HTTPException):
        return False


def start_server(home, request, *, call=subprocess.run, http=local_request, await_manager=wait_for_manager,
                 clock=time.monotonic, sleep=time.sleep):
    script = home / SERVER
    verify_server(script, request["expected_server_sha256"])
    if server_ready(script, call, http):
        return "already_running"
    if not compatible_launcher(home / APP / LAUNCHER):
        raise ValueError("remote_manager_start_launcher_changed")
    ready = lambda: dashboard_endpoint(home, call)
    failure = await_manager(home / APP, open_manager, ready, stable=True)
    if failure:
        raise ValueError(failure)
    endpoint = ready()
    if endpoint is None:
        raise ValueError("remote_manager_start_dashboard_unverified")
    _, record = endpoint
    port = record["port"]
    tokens = START_TOKEN.findall(http(port, "GET", "/", limit=64_000))
    if len(tokens) != 1 or ready() != endpoint:
        raise ValueError("remote_manager_start_dashboard_changed")
    verify_server(script, request["expected_server_sha256"])
    if time.time() >= request["expires_at"]:
        raise ValueError("remote_manager_start_request_expired")
    if server_ready(script, call, http):
        return "already_running"
    reply = decode_remote_json(http(port, "POST", "/api/rapbrain/start",
                                    headers={"X-RB-Launch-Token": tokens[0].decode("ascii")}))
    if type(reply) is not dict or reply.get("queued") is not True:
        if server_ready(script, call, http):
            return "already_running"
        raise ValueError("remote_manager_start_not_queued")
    deadline = clock() + 25
    while clock() < deadline:
        if server_ready(script, call, http):
            return "started"
        sleep(0.5)
    raise ValueError("remote_manager_start_health_unverified")


def advance_start_task(task, *, home=None, authorize=authorize_start, start=start_server):
    request = parse_start_task(task)
    authorize(task, request)
    return start(Path.home().resolve() if home is None else home, request)
