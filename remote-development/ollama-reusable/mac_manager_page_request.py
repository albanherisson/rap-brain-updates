"""Open the fixed local Rap Brain page after proving the reviewed server is ready."""

from pathlib import Path
import re
import subprocess
import time

from mac_manager_start_request import SERVER, local_request, start_server, server_ready
from mac_private_source_trial import github_file, keychain_token
from manager_remote_request import decode_remote_json


URL = "http://127.0.0.1:8765/"
FIELDS = {"schema", "id", "action", "expected_server_sha256", "expires_at",
          "authorization_commit"}


class PageUnverified(ValueError):
    """Opening may have occurred, but the visible URL could not be proven."""


def parse_page_task(task, now=None):
    current = time.time() if now is None else now
    if (type(task) is not dict or task.keys() != FIELDS
            or task["schema"] != "rapbrain-remote-task-v7"
            or task["action"] != "manager_open_page"
            or type(task["id"]) is not str
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", task["id"])
            or type(task["authorization_commit"]) is not str
            or not re.fullmatch(r"[0-9a-f]{40}", task["authorization_commit"])
            or type(task["expected_server_sha256"]) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", task["expected_server_sha256"])
            or type(task["expires_at"]) is not int
            or not current < task["expires_at"] <= current + 86400):
        raise ValueError("remote_manager_page_request_invalid")
    return {"schema": "rapbrain-manager-page-v1", "id": task["id"],
            "expected_server_sha256": task["expected_server_sha256"],
            "expires_at": task["expires_at"]}


def authorize_page(task, request, *, fetch=github_file, token=keychain_token):
    path = "remote-development/manager-page-authorizations/" + request["id"] + ".json"
    if decode_remote_json(fetch(path, token(), task["authorization_commit"])) != request:
        raise ValueError("remote_manager_page_authorization_mismatch")


def open_page(home, request, *, start=start_server, ready=server_ready,
              call=subprocess.run, http=local_request, clock=time.monotonic, sleep=time.sleep):
    server_state = start(home, request)
    if not ready(home / SERVER, subprocess.run, http):
        raise ValueError("remote_manager_page_server_unverified")
    if time.time() >= request["expires_at"]:
        raise ValueError("remote_manager_page_request_expired")
    try:
        opened = call(["/usr/bin/open", "-a", "Safari", URL], capture_output=True,
                      text=True, stdin=subprocess.DEVNULL, timeout=20)
    except subprocess.TimeoutExpired:
        raise PageUnverified("remote_manager_page_open_timeout") from None
    if opened.returncode:
        raise ValueError("remote_manager_page_open_refused")
    deadline = clock() + 15
    while clock() < deadline:
        try:
            observed = call(["/usr/bin/osascript", "-e",
                             'tell application "Safari" to get URL of front document'],
                            capture_output=True, text=True, stdin=subprocess.DEVNULL,
                            timeout=5)
        except subprocess.TimeoutExpired:
            observed = None
        if observed is not None and observed.returncode == 0 and observed.stdout.strip().rstrip("/") == URL.rstrip("/"):
            if ready(home / SERVER, subprocess.run, http):
                return {"state": "opened", "server": server_state, "page_url_verified": True}
            raise ValueError("remote_manager_page_server_unverified")
        sleep(0.5)
    raise PageUnverified("remote_manager_page_url_unverified")


def advance_page_task(task, *, home=None, authorize=authorize_page, open_ui=open_page):
    request = parse_page_task(task)
    authorize(task, request)
    return open_ui(Path.home().resolve() if home is None else Path(home), request)
