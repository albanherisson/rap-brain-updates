#!/usr/bin/env python3
"""Exercise a second launch during signed Manager update 15 on disposable copies."""

import functools
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import uuid
import urllib.request
from contextlib import closing

RAW = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
RUNNER = RAW + "cdb675c3b28ae30f619833fd71490564b630fae2/remote-development/mac_manager_handoff_trial.py"
RUNNER_SHA = "c68d0c9d85a4f82e9d9caf9ef4970fe40bed84098f9b3005d591b62d9bc6b783"
RELEASE = RAW + "bfce88ae32cb18967a59c0bfbe683349ac85310b/manager-stable/"
MANIFEST_SHA = "525942b65bb77cd9400ccf08eb9761d7746674da509ad46606db2ec6d66f0daa"
ARCHIVE_SHA = "42f91c69a313b8740be5f013d542148328ceb43d75daf9e1590e810c814d8fa1"
DASHBOARD_SHA = "cd698665767d379c312ada30cdcbebf0157fba6bda1f3aa501bb982d41872259"
HERE = Path(__file__).resolve()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def download(url, pin, limit):
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read(limit + 1)
        require(response.geturl() == url and 0 < len(raw) <= limit and sha(raw) == pin,
                "reopen_trial_dependency_changed")
    return raw


def load_runner(root):
    path = root / "handoff_runner.py"
    path.write_bytes(download(RUNNER, RUNNER_SHA, 50_000))
    spec = importlib.util.spec_from_file_location("reopen_handoff_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    (root / "trial_support.py").write_bytes(
        download(runner.SUPPORT_URL, runner.SUPPORT_SHA, 50_000))
    return runner


def probe_copy(launcher, port):
    home = Path.home().resolve()
    require(launcher == home / "Downloads/RapBrainManager_App_Beta14"
            / "Rap Brain Manager Beta 14.app/Contents/Resources/launch_manager.py"
            and home.parent.name.startswith("rapbrain-reopen-")
            and 1024 <= port <= 65535 and port not in (8765, 11434),
            "reopen_trial_probe_not_isolated")
    namespace = {"__file__": str(launcher), "__name__": "reopen_copy"}
    exec(compile(launcher.read_bytes(), str(launcher), "exec"), namespace)
    namespace["CHILD"] = namespace["CHILD"].replace("8765", str(port))
    sys.argv = [str(launcher), "--smoke-test", "--no-browser"]
    print("reopen_probe_exit=" + str(namespace["main"]()), flush=True)
    # Keep the process visible as a native error window would be, until the
    # isolated controller closes its stdin after both update checks.
    sys.stdin.buffer.read(1)


def run_trial(active_home, root):
    runner = load_runner(root)
    support = runner.load_support(root)
    helper_zip = support.fetch_helper()
    backup_reader = download(support.BACKUP_URL, support.BACKUP_SHA, 20_000)
    locale = {}
    exec(compile(download(runner.LOCALE_URL, runner.LOCALE_SHA, 20_000),
                 "locale_candidate.py", "exec"), locale)
    helper = root / "helper"
    runner.stage_reviewed_helper(support, helper_zip, backup_reader, locale, helper)
    sys.path.insert(0, str(helper))
    from app_bundle_backup import _copy_verified, inventory
    from creative_release import Refused
    from creative_transaction import atomic_write, safe_path
    from mac_offline_bootstrap_gate import assert_offline
    from manager_offline_lifecycle import MacOfflineManagerLifecycle
    from manager_update_recovery import recover_existing
    from manager_update_release import verify_archive, verify_manifest
    from manager_update_transaction import ManagerUpdateTransaction
    from pending_attempt_recovery import require_no_local_listener
    from strict_json import parse_signed_json

    signed = download(RELEASE + "manifest.json", MANIFEST_SHA, 65_536)
    archive = download(RELEASE + "update-15.zip", ARCHIVE_SHA, 100_000)
    issued = parse_signed_json(signed)["signed_payload"]["issued_at"]
    manifest = verify_manifest(signed, minimum_sequence=14, now=issued)
    files = verify_archive(archive, manifest)
    require(manifest["sequence"] == 15 and set(files) == {"app/launch_manager.py"},
            "reopen_trial_release_unexpected")

    live_app = safe_path(active_home / runner.APP_PATH, directory=True)
    live_source = safe_path(active_home / runner.SOURCE_PATH, directory=True)
    before = inventory(live_app)
    runner.checked_bytes(live_app / runner.LAUNCHER, support.LAUNCHER_SHA)
    runner.checked_bytes(live_app / runner.DASHBOARD, DASHBOARD_SHA)
    home = root / "home"
    app, source, state = home / runner.APP_PATH, home / runner.SOURCE_PATH, home / runner.STATE_PATH
    app.parent.mkdir(parents=True, mode=0o700)
    source.mkdir(parents=True, mode=0o700)
    state.mkdir(parents=True, mode=0o700)
    _copy_verified(live_app, app, before)
    launcher = app / runner.LAUNCHER
    support.run_checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                        "reopen_trial_original_signature_invalid")
    for name, pin in support.RUNTIME_SOURCES.items():
        (source / name).write_bytes(runner.checked_bytes(live_source / name, pin))

    data = source / "data"
    data.mkdir(mode=0o700)
    config = '{"model":"p0-fixture"}\n'
    (data / "ollama_model.json").write_text(config)
    db_path = data / "rapbrain.sqlite3"
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, status TEXT)")
        db.execute("CREATE TABLE trial_marker (value TEXT)")
        db.execute("INSERT INTO trial_marker VALUES ('synthetic')")

    port = runner.choose_port()
    tmp = root / "tmp"
    tmp.mkdir(mode=0o700)
    env = {"HOME": str(home), "TMPDIR": str(tmp), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
           "LC_ALL": "C", "LANG": "C", "RAP_BRAIN_PORT": str(port),
           "RAP_BRAIN_DATA": str(data), "OLLAMA_URL": "http://127.0.0.1:1"}
    for key, value in env.items():
        os.environ[key] = value

    attempt = uuid.uuid4().hex
    ticket = (secrets.token_hex(32) + "\n").encode()
    stage = state / ("handoff-" + attempt)
    stage.mkdir(mode=0o700)
    atomic_write(stage / "release.json", signed)
    atomic_write(stage / "release.zip", archive)
    atomic_write(state / "manager-accepted.json", b'{"sequence":14}')
    atomic_write(state / "bootstrap-intent.json", json.dumps({
        "id": attempt, "source": str(source), "launcher": str(launcher),
        "ticket_sha256": sha(ticket)}).encode())
    atomic_write(state / "maintenance.ticket", ticket)

    inspect_copy = runner.copy_inspector(home, port)
    competing = None
    probe_log = root / "reopen.log"

    def inspect(source_path, resource_path):
        report = inspect_copy(source_path, resource_path)
        report["manager_process_seen"] = competing is not None and competing.poll() is None
        return report

    def lifecycle(reopen):
        class CopyLifecycle(MacOfflineManagerLifecycle):
            def start_and_check(self):
                nonlocal competing
                if reopen:
                    require(competing is None, "reopen_trial_competing_process_reused")
                    with probe_log.open("xb") as log:
                        competing = subprocess.Popen(
                            [sys.executable, "-I", "-B", str(HERE), "--probe-copy", str(launcher), str(port)],
                            env=env, cwd=root, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
                    def probe_finished():
                        require(competing.poll() is None, "reopen_trial_probe_exited_early")
                        output = probe_log.read_bytes()
                        return output if b"reopen_probe_exit=" in output else None

                    result = runner.wait_for(probe_finished, "reopen_trial_probe_timeout")
                    require(b"Manager update state invalid" in result and b"reopen_probe_exit=2" in result,
                            "reopen_trial_startup_guard_not_reproduced")
                return super().start_and_check()

        return CopyLifecycle(source, launcher, state, signed, issued_recovery=True,
                             port=port, inspector=inspect)

    original = lifecycle(True)
    try:
        try:
            ManagerUpdateTransaction(source, launcher, state, original).install_handed_off(signed, archive, attempt)
        except Refused as error:
            require(str(error) == "rapbrain_or_manager_still_running", "reopen_trial_unexpected_refusal")
        else:
            raise ValueError("reopen_trial_expected_refusal_missing")
        record = json.loads((state / "manager-transaction.json").read_bytes())
        require(record["phase"] == "switched" and launcher.read_bytes() == files["app/launch_manager.py"]
                and not list(state.glob("restart-*.log")), "reopen_trial_failed_state_not_reproduced")
        require((state / "maintenance.ticket").read_bytes() == ticket, "reopen_trial_ticket_lost")
    finally:
        if competing is not None:
            competing.stdin.close()
            runner.stop_retained(competing)

    recovery = lifecycle(False)
    try:
        result = recover_existing(source, launcher, state, offline=functools.partial(assert_offline, inspector=inspect),
                                  lifecycle_factory=lambda *args, **kwargs: recovery)
    finally:
        if recovery.owned is not None:
            runner.stop_retained(recovery.owned.current)
    require(result["state"] == "rolled_back" and inventory(app) == before
            and not (state / "maintenance.ticket").exists()
            and not (state / "bootstrap-intent.json").exists(), "reopen_trial_recovery_incomplete")
    require_no_local_listener(port)
    smoke = subprocess.run([sys.executable, "-I", "-B", str(HERE), "--probe-copy", str(launcher), str(port)],
                           env=env, cwd=root, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    require(smoke.returncode == 0 and b"reopen_probe_exit=0" in smoke.stdout,
            "reopen_trial_restored_dashboard_failed")
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
        require(db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
                and db.execute("SELECT value FROM trial_marker").fetchall() == [("synthetic",)],
                "reopen_trial_database_changed")
    require((data / "ollama_model.json").read_text() == config and inventory(live_app) == before
            and json.loads((state / "manager-accepted.json").read_bytes()) == {"sequence": 14},
            "reopen_trial_baseline_not_preserved")
    return {"status": "pass", "sequence": 15, "reopened_copy": "startup_refused",
            "handoff": "switched_before_server_restart", "reason": "rapbrain_or_manager_still_running",
            "recovery": "rolled_back", "restored_dashboard": "verified", "macos_codesign": "verified",
            "synthetic_sqlite_and_config": "preserved", "active_app_unchanged": True}


def main():
    require(sys.platform == "darwin", "reopen_trial_macos_required")
    if len(sys.argv) == 4 and sys.argv[1] == "--probe-copy":
        probe_copy(Path(sys.argv[2]), int(sys.argv[3]))
        return
    require(len(sys.argv) == 1, "reopen_trial_invalid_arguments")
    with tempfile.TemporaryDirectory(prefix="rapbrain-reopen-") as folder:
        print(json.dumps(run_trial(Path.home().resolve(), Path(folder).resolve())), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        detail = str(error)
        print(json.dumps({"status": "failed", "reason": detail if re.fullmatch(
            r"[a-zA-Z0-9_]+", detail) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
