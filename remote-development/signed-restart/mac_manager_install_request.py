"""Authorize one release via the private repo and hand it to the installed Manager."""

from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

from mac_private_source_trial import github_file, keychain_token
from manager_remote_request import (REMOTE_FIELDS, REMOTE_REQUEST_SCHEMA, REMOTE_TERMINAL,
                                    decode_remote_json, lock_remote_directory, queue_remote_request,
                                    read_remote_json, remote_directory, remote_receipt,
                                    save_remote_receipt, validate_remote_request)


APP = Path("Downloads/RapBrainManager_App_Beta14/Rap Brain Manager Beta 14.app")
LAUNCHER = Path("Contents/Resources/launch_manager.py")
LAUNCHER_SHA = "ceda87b7655d643ca6e9dc66afa0f5d3e0d20857abd2e8c202b8a1978b86a660"
CORRECTED_LAUNCHER_SHA = "642dc6d2595cca8f5ad6a189dc7362cca74080344beb9e9c331880b157869c7e"
HANDOFF_RECEIPT = Path("Downloads/RapBrainManagerBackups/secure-update/manager-handoff-result.json")
OPEN_WINDOWS = (10, 20, 40)
REOPEN_POLL = 0.75
RESTART_HELPER = "mac_signed_server_restart.py"
RESTART_SHA = "7d3b2d04b2d3c09ab100f9e9c781b4720daabcbcec55009f083386abadcad7dc"


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


def open_manager(app, call=subprocess.run, *, background=False):
    if app.resolve() != app or not app.is_dir():
        raise ValueError("remote_manager_bundle_path_invalid")
    try:
        signature = call(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                         capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("remote_manager_codesign_unavailable") from None
    if signature.returncode != 0:
        raise ValueError("remote_manager_codesign_refused")
    args = ["/usr/bin/open", "-g", str(app)] if background else ["/usr/bin/open", str(app)]
    try:
        result = call(args, capture_output=True, stdin=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("remote_manager_launchservices_unavailable") from None
    if result.returncode:
        raise ValueError("remote_manager_launchservices_refused")
    return True


def runtime_directories(call):
    roots = {Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()}
    try:
        result = call(["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"], capture_output=True,
                      text=True, stdin=subprocess.DEVNULL, timeout=2)
        if result.returncode == 0 and not result.stderr and len(result.stdout) <= 1024:
            root = Path(result.stdout.strip())
            if root.is_absolute():
                roots.add(root.resolve())
    except (OSError, subprocess.SubprocessError):
        pass
    found = {}
    for root in roots:
        try:
            for path in root.glob("rapbrain-manager-beta-*"):
                info = path.lstat()
                if (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                        and not info.st_mode & 0o077):
                    found[path] = info.st_mtime_ns
        except OSError:
            continue
    return sorted(found, key=found.get, reverse=True)[:8]


def dashboard_record(runtime):
    try:
        fd = os.open(runtime / "port.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or not 0 < info.st_size <= 256:
                return None
            record = decode_remote_json(stream.read(257))
    except (OSError, ValueError):
        return None
    if (type(record) is dict and set(record) == {"port", "pid"}
            and type(record["port"]) is int and 1024 <= record["port"] <= 65535
            and record["port"] not in (8765, 11434)
            and type(record["pid"]) is int and record["pid"] > 1):
        return record
    return None


def process_is_live(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def find_verified_dashboard(home, attempt, state, *, call=subprocess.run, connect=http.client.HTTPConnection,
                    live=process_is_live, diagnostics=None):
    receipt_path = home / HANDOFF_RECEIPT
    try:
        if receipt_path.parent.resolve() != receipt_path.parent:
            return None
        expected = read_remote_json(receipt_path)
    except (OSError, ValueError):
        return None
    if (type(expected) is not dict or expected.get("attempt") != attempt
            or expected.get("state") != state):
        return None

    # The Manager writes this port/PID pair in its owner-only runtime
    # directory. The loopback GET carries no token or attempt identifier.
    # A live reply must match the entire private handoff receipt.
    for runtime in runtime_directories(call):
        record = dashboard_record(runtime)
        if record is None:
            continue
        if diagnostics is not None:
            diagnostics["dashboard_port_declared"] = True
        port, pid = record["port"], record["pid"]
        if not live(pid):
            continue
        if diagnostics is not None:
            diagnostics["dashboard_pid_live"] = True
        try:
            connection = connect("127.0.0.1", port, timeout=2)
            try:
                connection.request("GET", "/api/rapbrain/manager-update-state")
                response = connection.getresponse()
                if (response.status != 200
                        or response.getheader("Content-Type", "").split(";")[0] != "application/json"):
                    continue
                receipt = decode_remote_json(response.read(4097))
                if diagnostics is not None:
                    diagnostics["dashboard_http_responded"] = True
            finally:
                connection.close()
            if (receipt == expected and live(pid) and dashboard_record(runtime) == record
                    and read_remote_json(receipt_path) == expected):
                return runtime, record
        except (OSError, ValueError, http.client.HTTPException):
            continue
    return None



def dashboard_ready(home, attempt, state, *, call=subprocess.run, connect=http.client.HTTPConnection,
                    live=process_is_live, diagnostics=None):
    return find_verified_dashboard(home, attempt, state, call=call, connect=connect,
                                   live=live, diagnostics=diagnostics) is not None

def wait_for_manager(app, opener, ready, *, stable=False, clock=time.monotonic, sleep=time.sleep):
    if ready():
        return None
    launch_accepted = False
    last_error = "remote_manager_launchservices_refused"
    for attempt_number, timeout in enumerate(OPEN_WINDOWS):
        try:
            if opener is open_manager:
                opened = open_manager(app, background=attempt_number == 1)
            else:
                opened = opener(app)
            launch_accepted |= bool(opened)
        except ValueError as error:
            last_error = str(error)
            if last_error in ("remote_manager_bundle_path_invalid", "remote_manager_codesign_refused"):
                return last_error
        except (OSError, subprocess.SubprocessError):
            last_error = "remote_manager_launchservices_unavailable"
        deadline = clock() + timeout
        previous = False
        while clock() < deadline:
            observed = ready()
            if observed and (previous or not stable):
                return None
            previous = observed
            sleep(min(REOPEN_POLL, max(0, deadline - clock())))
    return "remote_manager_dashboard_unverified" if launch_accepted else last_error


def reopen_manager(home, attempt, state, *, opener=open_manager, probe=dashboard_ready,
                   clock=time.monotonic, sleep=time.sleep, details=None):
    failure = wait_for_manager(home / APP, opener, lambda: probe(home, attempt, state),
                               stable=True, clock=clock, sleep=sleep)
    if details is not None and failure is not None:
        details["reason"] = failure
    return failure is None


def restart_foreign_server(home, request, call=subprocess.run, *, installed=False):
    script = Path(__file__).resolve().with_name(RESTART_HELPER)
    if script.is_symlink() or not script.is_file() or hashlib.sha256(script.read_bytes()).hexdigest() != RESTART_SHA:
        raise ValueError("remote_manager_restart_code_mismatch")
    with tempfile.TemporaryDirectory(prefix="rapbrain-authorized-server-restart-") as temporary:
        root = Path(temporary).resolve()
        env = {"HOME": str(home), "TMPDIR": str(root), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        command = [sys.executable, "-I", "-B", str(script)]
        if installed:
            command.append("--installed")
        result = call(command, cwd=root, env=env,
                      input=json.dumps(request).encode(), capture_output=True, timeout=120)
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
        return proof["server"]


def compatible_launcher(launcher):
    return (launcher.resolve() == launcher and launcher.is_file()
            and hashlib.sha256(launcher.read_bytes()).hexdigest()
            in (LAUNCHER_SHA, CORRECTED_LAUNCHER_SHA))


def install_receipt(home, record):
    path = home / HANDOFF_RECEIPT
    if path.parent.resolve() != path.parent:
        raise ValueError("unsafe_remote_manager_handoff_receipt")
    receipt = read_remote_json(path)
    if (type(receipt) is not dict or receipt.get("attempt") != record.get("attempt")
            or receipt.get("state") not in REMOTE_TERMINAL):
        return None
    result = {"state": receipt["state"]}
    reason = receipt.get("reason")
    if type(reason) is str and re.fullmatch(r"[a-zA-Z0-9_]{1,80}", reason):
        result["reason"] = reason
    return result


@contextmanager
def request_lock(directory):
    try:
        fd = lock_remote_directory(directory)
    except BlockingIOError:
        yield False
    else:
        try:
            yield True
        finally:
            os.close(fd)


def terminal_result(record):
    return {key: record[key] for key in ("state", "reason", "manager_reopened") if key in record}


def advance_install_task(task, *, home=None, authorize=authorize_install_task,
                         opener=open_manager, restart=restart_foreign_server,
                         reopener=reopen_manager, await_start=wait_for_manager):
    home = Path.home().resolve() if home is None else Path(home)
    request = parse_install_task(task)
    authorize(task, request)
    directory = remote_directory(home, create=True)
    with request_lock(directory) as acquired:
        if not acquired:
            return {"state": "pending"}
        record = remote_receipt(directory, request)
        stage = record["state"] if record else None
        if stage in REMOTE_TERMINAL:
            return terminal_result(record)
        if stage == "handoff":
            finished = install_receipt(home, record)
            if finished is None:
                return {"state": "pending"} if time.time() < request["expires_at"] else {"state": "check_required"}
        else:
            if stage == "dispatching":
                return {"state": "pending"} if time.time() < request["expires_at"] else {"state": "check_required"}
            if time.time() >= request["expires_at"]:
                save_remote_receipt(directory, request, "expired")
                return {"state": "expired"}
            if stage == "waiting_foreign_server":
                try:
                    restart(home, request)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                    if isinstance(exc, ValueError) and str(exc) in (
                            "worker_busy_or_maintenance", "jobs_active_or_unknown_status"):
                        return {"state": "pending"}
                    record = save_remote_receipt(directory, request, "refused", reason=str(exc))
                    return {"state": "refused", "reason": record.get("reason", "server_stop_refused")}
                save_remote_receipt(directory, request, "server_released")
                return {"state": "pending"}
            if stage is not None:
                return {"state": "pending"}
            if not compatible_launcher(home / APP / LAUNCHER):
                return {"state": "refused", "reason": "remote_manager_launcher_upgrade_required"}
            queue_remote_request(directory, request)

    # The launched Manager must be able to take this same lock to consume the
    # request while LaunchServices is starting it or reporting an error.
    if stage != "handoff":
        failure = await_start(home / APP, opener, lambda: remote_receipt(directory, request) is not None)
        if failure is None:
            return {"state": "pending"}
        with request_lock(directory) as acquired:
            if not acquired or remote_receipt(directory, request) is not None:
                return {"state": "pending"}
            save_remote_receipt(directory, request, "refused", reason=failure)
            return {"state": "refused", "reason": failure}

    reopened = False
    if finished["state"] in ("committed", "rolled_back"):
        details = {}
        if reopener is reopen_manager:
            reopened = reopen_manager(home, record["attempt"], finished["state"], opener=opener, details=details)
        else:
            reopened = reopener(home, record["attempt"], finished["state"], opener=opener)
        if not reopened and "reason" not in finished:
            finished["reason"] = details.get("reason", "remote_manager_dashboard_unverified")
    with request_lock(directory) as acquired:
        if not acquired:
            return {"state": "pending"}
        current = remote_receipt(directory, request)
        if current != record:
            if current and current["state"] in REMOTE_TERMINAL:
                return terminal_result(current)
            return {"state": "pending"}
        save_remote_receipt(directory, request, **finished, attempt=record["attempt"], manager_reopened=reopened)
        return finished | {"manager_reopened": reopened}
