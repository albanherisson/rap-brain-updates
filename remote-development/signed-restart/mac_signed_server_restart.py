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
    result = command(["/bin/ps", "-axww", "-o", "pid=,ppid=,pgid=,uid=,command="])
    require(result.returncode == 0 and not result.stderr
            and 0 < len(result.stdout) <= 2_000_000, "restart_process_inventory_failed")
    rows = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 4)
        require(len(parts) == 5 and all(re.fullmatch(r"-?[0-9]+", value) for value in parts[:4]),
                "restart_process_inventory_invalid")
        pid, ppid, pgid, uid = map(int, parts[:4])
        require(pid not in rows, "restart_process_inventory_invalid")
        rows[pid] = (ppid, pgid, uid, parts[4])
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


def verify_restart_release(request, state, script):
    from manager_update_release import CHANNEL, fetch, verify_manifest
    from pending_attempt_recovery import _private_json

    receipt = _private_json(state / "manager-accepted.json", 4096)
    require(type(receipt) is dict and set(receipt) == {"sequence"}
            and type(receipt["sequence"]) is int and receipt["sequence"] >= 1,
            "restart_installed_receipt_invalid")
    require(time.time() < request["expires_at"], "restart_request_expired")
    raw = fetch(CHANNEL, 65_536)
    require(hashlib.sha256(raw).hexdigest() == request["manifest_sha256"],
            "restart_release_changed")
    manifest = verify_manifest(raw, minimum_sequence=receipt["sequence"])
    require(manifest["sequence"] == request["sequence"]
            and manifest["required_server_sha256"] == request["expected_server_sha256"],
            "restart_release_baseline_mismatch")
    require(server_digest(script) == request["expected_server_sha256"],
            "restart_server_version_changed")


def server_digest(script):
    with script.open("rb") as stream:
        data = stream.read(250_001)
    require(0 < len(data) <= 250_000, "restart_server_size_invalid")
    return hashlib.sha256(data).hexdigest()


def prepare_restart(home, request):
    from authenticated_runtime_client import read_runtime_proof, assert_owned_listener
    from creative_readiness import assert_no_pending_jobs
    from creative_transaction import safe_path
    from owned_graceful_stop import _stop_response
    from pending_attempt_recovery import _private_json
    from process_start_identity import read_start
    from worker_activity_gate import _lock, _state, begin_maintenance

    parent = listener()
    if parent is None:
        return "already_stopped"
    source = safe_path(home / "Downloads/rap-brain", directory=True)
    script = safe_path(source / "server.py")
    state = _state(home / "Downloads/RapBrainManagerBackups/secure-update")
    verify_restart_release(request, state, script)
    marker = state / "maintenance.ticket"
    require(not os.path.lexists(marker) and not any(os.path.lexists(state / name) for name in INTENTS),
            "restart_existing_maintenance")
    for name in ("manager-transaction.json", "bootstrap-transaction.json", "transaction.json"):
        if os.path.lexists(state / name):
            journal = _private_json(state / name, 65_536)
            require(journal.get("phase") in ("committed", "rolled_back", "aborted", "restored_stopped"),
                    "restart_existing_maintenance")

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
    require(sys.platform == "darwin" and len(sys.argv) == 1, "restart_macos_required")
    if listener() is None:
        print(json.dumps({"status": "pass", "server": "already_stopped"}))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mac_manager_sign_request import verified_helpers
    from manager_remote_request import decode_remote_json, validate_remote_request

    raw = sys.stdin.buffer.read(4097)
    require(0 < len(raw) <= 4096, "restart_request_size")
    request = validate_remote_request(decode_remote_json(raw))
    home = Path.home().resolve()
    with tempfile.TemporaryDirectory(prefix="rapbrain-restart-") as directory:
        helper, _ = verified_helpers(home, Path(directory).resolve())
        sys.path.insert(0, str(helper))
        result = prepare_restart(home, request)
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
