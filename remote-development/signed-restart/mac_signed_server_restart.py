#!/usr/bin/env python3
"""Release an authenticated Rap Brain listener for an authorized signed update."""

import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request


PORT = ("https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
           "169b1f1f735dee92f083a617883bb1245e655f2b/remote-development/mac_manager_signed_copy_trial.py")
SUPPORT_SHA = "9edb62dfbe1ce5b9bd22e20d2c0627676d7e0c6619f9f02a9635a2c071663ba1"
LOCALE = ("https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
          "15638ef4c6c93f266c208e6ed9d20049b14d7a36/decoder-next/manager_locale_repair_candidate.py")
LOCALE_SHA = "a3e2771286abd02fadecb926ff17e2a42aff32f55785743076fa630fcff85945"
PORT = 8765
TOKEN = re.compile(r"(?:^|\s)RB_UPDATE_PROBE_TOKEN=([0-9a-f]{64})(?=\s|$)")
INTENTS = ("bootstrap-intent.json", "maintenance-intent.json")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def command(args):
    return subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          env={"LC_ALL": "C", "LANG": "C", "PATH": "/usr/bin:/bin"}, timeout=8)


def listener():
    result = command(["/usr/sbin/lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN", "-Fp"])
    if result.returncode == 1 and not result.stdout and not result.stderr:
        return None
    lines = result.stdout.splitlines()
    pids = [int(line[1:]) for line in lines if re.fullmatch(r"p[0-9]+", line)]
    require(result.returncode == 0 and not result.stderr and len(pids) == 1
            and all(re.fullmatch(r"(?:p[0-9]+|f[0-9]+[a-zA-Z]?)", line) for line in lines),
            "restart_listener_unproven")
    return pids[0]


def process_rows():
    result = command(["/bin/ps", "-axww", "-o", "pid=,ppid=,pgid=,uid=,stat=,command="])
    require(result.returncode == 0 and not result.stderr
            and 0 < len(result.stdout) <= 2_000_000, "restart_process_inventory_failed")
    rows = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 5)
        require(len(parts) == 6 and all(re.fullmatch(r"-?[0-9]+", value) for value in parts[:4])
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9+<>=*:-]*", parts[4]),
                "restart_process_inventory_invalid")
        pid, ppid, pgid, uid = map(int, parts[:4])
        require(pid not in rows, "restart_process_inventory_invalid")
        # A child that exited can remain in ps until its owner calls waitpid().
        # It has no running code. The loop also requires the listening port to be closed.
        if not parts[4].startswith("Z"):
            rows[pid] = (ppid, pgid, uid, parts[5])
    return rows


def process_group(parent, script):
    rows = process_rows()
    entry = rows.get(parent)
    require(entry is not None and entry[1:3] == (parent, os.getuid())
            and entry[3].endswith(" -u " + str(script)), "restart_server_outside_manager")
    children = [(pid, row) for pid, row in rows.items() if pid != parent and row[1] == parent]
    require(len(children) == 1, "restart_worker_unproven")
    worker, child = children[0]
    require(child[:3] == (parent, parent, os.getuid())
            and child[3].endswith(" " + str(script) + " --worker"), "restart_worker_unproven")
    return worker


def runtime_token(parent):
    # Read the previous Manager's local authentication token without printing it.
    result = command(["/bin/ps", "-E", "-ww", "-p", str(parent), "-o", "command="])
    matches = TOKEN.findall(result.stdout)
    require(result.returncode == 0 and not result.stderr
            and len(result.stdout) <= 2_000_000 and len(matches) == 1, "restart_runtime_token_unavailable")
    return matches[0]


def release_own_ticket(path, ticket):
    # This operation never edits an updater journal or another maintenance ticket.
    if not path.is_symlink() and path.is_file() and path.read_bytes() == ticket:
        path.unlink()


def verify_restart_release(request, state, script, *, installed_commit=None):
    from manager_update_release import CHANNEL, NoRedirect, fetch, verify_manifest
    from pending_attempt_recovery import _private_json
    from strict_json import parse_signed_json

    receipt = _private_json(state / "manager-accepted.json", 4096)
    require(type(receipt) is dict and set(receipt) == {"sequence"}
            and type(receipt["sequence"]) is int and receipt["sequence"] >= 1,
            "restart_installed_receipt_invalid")
    require(time.time() < request["expires_at"], "restart_request_expired")
    verify_options = {"minimum_sequence": receipt["sequence"]}
    if installed_commit is None:
        raw = fetch(CHANNEL, 65_536)
    else:
        require(re.fullmatch(r"[a-f0-9]{40}", installed_commit) is not None,
                "restart_release_commit_invalid")
        channel = ("https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
                   + installed_commit + "/manager-stable/manifest.json")
        opener = urllib.request.build_opener(NoRedirect())
        url = urllib.request.Request(channel, headers={"Accept-Encoding": "identity"})
        with opener.open(url, timeout=20) as response:
            require(response.status == 200 and response.geturl() == channel, "restart_release_changed")
            raw = response.read(65_537)
        require(0 < len(raw) <= 65_536, "restart_release_size")
    require(hashlib.sha256(raw).hexdigest() == request["manifest_sha256"],
            "restart_release_changed")
    if installed_commit is not None:
        # Installation freshness applies at installation. The new stop grant has its own expiry.
        envelope = parse_signed_json(raw)
        signed = envelope.get("signed_payload") if type(envelope) is dict else None
        issued = signed.get("issued_at") if type(signed) is dict else None
        require(type(issued) is int and 0 <= issued <= time.time(), "restart_release_issued_at_invalid")
        verify_options = {"minimum_sequence": receipt["sequence"] - 1, "now": issued}
    manifest = verify_manifest(raw, **verify_options)
    expected = manifest["required_server_sha256"]
    if installed_commit is not None:
        require(receipt["sequence"] == manifest["sequence"], "restart_installed_sequence_mismatch")
        expected = next((member["payload_sha256"] for member in manifest["files"]
                         if member["path"] == "server.py"), expected)
    require(manifest["sequence"] == request["sequence"]
            and expected == request["expected_server_sha256"],
            "restart_release_baseline_mismatch")
    require(server_digest(script) == request["expected_server_sha256"],
            "restart_server_version_changed")


def server_digest(script):
    with script.open("rb") as stream:
        data = stream.read(250_001)
    require(0 < len(data) <= 250_000, "restart_server_size_invalid")
    return hashlib.sha256(data).hexdigest()


def prepare_restart(home, request, *, installed_commit=None):
    from authenticated_runtime_client import read_runtime_proof, assert_owned_listener
    from creative_readiness import assert_no_pending_jobs
    from creative_transaction import safe_path
    from owned_graceful_stop import _stop_response
    from pending_attempt_recovery import _private_json
    from process_start_identity import read_start
    from worker_activity_gate import _lock, _state, begin_maintenance

    parent = listener()
    if parent is None and installed_commit is None:
        return "already_stopped"
    source = safe_path(home / "Downloads/rap-brain", directory=True)
    script = safe_path(source / "server.py")
    state = _state(home / "Downloads/RapBrainManagerBackups/secure-update")
    verify_restart_release(request, state, script, installed_commit=installed_commit)
    marker = state / "maintenance.ticket"
    require(not os.path.lexists(marker) and not any(os.path.lexists(state / name) for name in INTENTS),
            "restart_existing_maintenance")
    for name in ("manager-transaction.json", "bootstrap-transaction.json", "transaction.json"):
        if os.path.lexists(state / name):
            journal = _private_json(state / name, 65_536)
            require(journal.get("phase") in ("committed", "rolled_back", "aborted", "restored_stopped"),
                    "restart_existing_maintenance")

    if parent is None:
        return "already_stopped"
    worker = process_group(parent, script)
    token = runtime_token(parent)
    identity = read_start(parent), read_start(worker)
    proof = read_runtime_proof(PORT, token, expected_parent_pid=parent)
    require(proof["worker_pid"] == worker, "restart_worker_unproven")
    ticket = (secrets.token_hex(32) + "\n").encode("ascii")
    try:
        begin_maintenance(state, ticket)
        admission = _lock(state, "admission.lock", fcntl.LOCK_EX)
        try:
            job = _lock(state, "worker-job.lock", fcntl.LOCK_EX)
            try:
                require(marker.read_bytes() == ticket
                        and not any(os.path.lexists(state / name) for name in INTENTS),
                        "restart_maintenance_changed")
                assert_no_pending_jobs(source)
                require(process_group(parent, script) == worker
                        and (read_start(parent), read_start(worker)) == identity,
                        "restart_process_identity_changed")
                proof = read_runtime_proof(PORT, token, expected_parent_pid=parent)
                require(proof["worker_pid"] == worker, "restart_worker_unproven")
            finally:
                os.close(job)
        finally:
            os.close(admission)
        require(time.time() < request["expires_at"], "restart_request_expired")
        require(server_digest(script) == request["expected_server_sha256"],
                "restart_server_version_changed")
        assert_owned_listener(PORT, parent)
        connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=4)
        try:
            connection.request("POST", "/api/manager-update-stop", body=b"", headers={
                "X-RB-Update-Token": token,
                "X-RB-Update-Ticket": ticket[:-1].decode("ascii"),
            })
            response = connection.getresponse()
            require(response.status == 202, "restart_server_refused_stop")
            _stop_response(response.read(129))
        finally:
            connection.close()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if listener() is None:
                rows = process_rows()
                if parent not in rows and worker not in rows and not any(row[1] == parent for row in rows.values()):
                    return "stopped"
            time.sleep(0.15)
        raise ValueError("restart_server_exit_unverified")
    finally:
        release_own_ticket(marker, ticket)


def main():
    require(sys.platform == "darwin" and sys.argv[1:] in ([], ["--installed"]), "restart_macos_required")
    if not sys.argv[1:] and listener() is None:
        print(json.dumps({"status": "pass", "server": "already_stopped"}))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mac_manager_sign_request import verified_helpers
    from manager_remote_request import decode_remote_json, validate_remote_request

    raw = sys.stdin.buffer.read(4097)
    require(0 < len(raw) <= 4096, "restart_request_size")
    request = decode_remote_json(raw)
    installed_commit = None
    if sys.argv[1:]:
        require(type(request) is dict, "restart_request_invalid")
        installed_commit = request.pop("release_commit", None)
        require(type(installed_commit) is str and re.fullmatch(r"[a-f0-9]{40}", installed_commit),
                "restart_release_commit_invalid")
    validate_remote_request(request)
    home = Path.home().resolve()
    with tempfile.TemporaryDirectory(prefix="rapbrain-restart-") as directory:
        helper, _ = verified_helpers(home, Path(directory).resolve())
        sys.path.insert(0, str(helper))
        result = prepare_restart(home, request, installed_commit=installed_commit)
    print(json.dumps({"status": "pass", "server": result}))


if __name__ == "__main__":
    def interrupted(_number, _frame):
        raise KeyboardInterrupt

    for signum in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        main()
    except (OSError, ValueError, RuntimeError, http.client.HTTPException,
            subprocess.SubprocessError, KeyboardInterrupt) as error:
        reason = str(error)
        print(json.dumps({"status": "refused", "reason": reason if re.fullmatch(
            r"[a-z0-9_]+", reason) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
