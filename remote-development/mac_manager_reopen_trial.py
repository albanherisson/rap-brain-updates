#!/usr/bin/env python3
"""Exercise a second launch during signed Manager update 15 on disposable copies."""

import base64
import functools
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.request
import zipfile
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
    code = namespace["main"]()
    print("reopen_probe_exit=" + str(code), flush=True)
    if code == 42:
        # Model the short time required by the native window to close.
        time.sleep(1.5)
        return
    # Keep the process visible as a native error window would be, until the
    # isolated controller closes its stdin after both update checks.
    sys.stdin.buffer.read(1)


def sign_fixed_trial(support, fix, manifest, payload, root):
    from creative_release import canonical

    member = "app/launch_manager.py"
    candidate = fix.build_launcher(payload[member])
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(member, candidate)
    archive = stream.getvalue()
    now = int(time.time())
    body = manifest | {
        "issued_at": now - 1,
        "expires_at": now + 3600,
        "archive_sha256": sha(archive),
        "archive_bytes": len(archive),
        "files": [manifest["files"][0] | {"payload_sha256": sha(candidate)}],
    }
    public, signature = support.sign_ephemeral(canonical(body), root)
    signed = canonical({
        "signed_payload": body,
        "public_key_base64": base64.b64encode(public).decode("ascii"),
        "signature_algorithm": "Ed25519",
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    })
    return signed, archive, sha(public)


def run_trial(active_home, root, fix=None, *, fail_health=False):
    runner = load_runner(root)
    support = runner.load_support(root)
    helper_zip = support.fetch_helper()
    backup_reader = download(support.BACKUP_URL, support.BACKUP_SHA, 20_000)
    locale = {}
    exec(compile(download(runner.LOCALE_URL, runner.LOCALE_SHA, 20_000),
                 "locale_candidate.py", "exec"), locale)
    helper = root / "helper"
    runner.stage_reviewed_helper(support, helper_zip, backup_reader, locale, helper)
    if fix is not None:
        for name, raw in fix.build_helpers(helper).items():
            (helper / name).write_bytes(raw)
    sys.path.insert(0, str(helper))
    from app_bundle_backup import _copy_verified, inventory
    from bootstrap_release import PUBLISHER_PIN
    from creative_release import Refused
    from creative_transaction import atomic_write, safe_path
    from mac_offline_bootstrap_gate import assert_offline
    from manager_offline_lifecycle import MacOfflineManagerLifecycle
    from manager_update_recovery import recover_existing
    from manager_update_helper import report_result
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
    pin = PUBLISHER_PIN
    if fix is not None:
        signed, archive, pin = sign_fixed_trial(support, fix, manifest, files, root)
        manifest = verify_manifest(signed, minimum_sequence=14, pinned_key=pin)
        files = verify_archive(archive, manifest)

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
    for name, expected in support.RUNTIME_SOURCES.items():
        (source / name).write_bytes(runner.checked_bytes(live_source / name, expected))

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
    manager_seen = False
    probe_log = root / "reopen.log"

    def inspect(source_path, resource_path):
        nonlocal manager_seen
        report = inspect_copy(source_path, resource_path)
        report["manager_process_seen"] = competing is not None and competing.poll() is None
        manager_seen |= report["manager_process_seen"]
        return report

    def lifecycle(reopen):
        class CopyLifecycle(MacOfflineManagerLifecycle):
            def start_and_check(self):
                nonlocal competing
                candidate = self._code_state() == "candidate"
                if reopen and candidate:
                    require(competing is None, "reopen_trial_competing_process_reused")
                    with probe_log.open("xb") as log:
                        competing = subprocess.Popen(
                            [sys.executable, "-I", "-B", str(HERE), "--probe-copy", str(launcher), str(port)],
                            env=env, cwd=root, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
                    def probe_finished():
                        output = probe_log.read_bytes()
                        return output if re.search(rb"reopen_probe_exit=\d+\n", output) else None

                    result = runner.wait_for(probe_finished, "reopen_trial_probe_timeout")
                    if fix is None:
                        require(b"Manager update state invalid" in result and b"reopen_probe_exit=2" in result,
                                "reopen_trial_startup_guard_not_reproduced")
                    else:
                        require(b"reopen_probe_exit=42" in result, "reopen_trial_did_not_yield")
                healthy = super().start_and_check()
                if fail_health and candidate and healthy:
                    raise Refused("manager_health_failed")
                return healthy

        return CopyLifecycle(source, launcher, state, signed, issued_recovery=True,
                             pinned_key=pin, port=port, inspector=inspect)

    original = lifecycle(True)
    try:
        if fix is not None:
            result = ManagerUpdateTransaction(source, launcher, state, original, pinned_key=pin).install_handed_off(
                signed, archive, attempt)
            receipt = report_result(state, attempt, result)
            require(manager_seen, "reopen_trial_contention_not_observed")
            expected_state = "rolled_back" if fail_health else "committed"
            require(receipt["state"] == expected_state, "reopen_trial_fixed_outcome_unexpected")
            if fail_health:
                require(receipt.get("reason") == "manager_health_failed" and inventory(app) == before,
                        "reopen_trial_reason_or_rollback_missing")
            else:
                require(launcher.read_bytes() == files["app/launch_manager.py"],
                        "reopen_trial_fixed_launcher_missing")
            return verify_completion(runner, live_app, before, app, launcher, state, db_path, config, port,
                                     root, env, receipt, code_signature_check=support.run_checked,
                                     reason="manager_health_failed" if fail_health else None)
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
        if fix is not None and original.owned is not None:
            runner.stop_retained(original.owned.current)

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


def verify_completion(runner, live_app, before, app, launcher, state, db_path, config, port,
                      root, env, receipt, *, code_signature_check, reason):
    from app_bundle_backup import inventory
    from pending_attempt_recovery import require_no_local_listener

    require(not (state / "maintenance.ticket").exists() and not (state / "bootstrap-intent.json").exists(),
            "reopen_trial_ticket_left")
    require_no_local_listener(port)
    code_signature_check(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                         "reopen_trial_final_signature_invalid")
    smoke = subprocess.run([sys.executable, "-I", "-B", str(HERE), "--probe-copy", str(launcher), str(port)],
                           env=env, cwd=root, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    require(smoke.returncode == 0 and b"reopen_probe_exit=0" in smoke.stdout,
            "reopen_trial_fixed_dashboard_failed")
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
        require(db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
                and db.execute("SELECT value FROM trial_marker").fetchall() == [("synthetic",)],
                "reopen_trial_database_changed")
    expected_sequence = 15 if receipt["state"] == "committed" else 14
    require((db_path.parent / "ollama_model.json").read_text() == config and inventory(live_app) == before
            and json.loads((state / "manager-accepted.json").read_bytes()) == {"sequence": expected_sequence},
            "reopen_trial_baseline_not_preserved")
    return {"status": "pass", "reopened_copy": "yielded", "outcome": receipt["state"],
            "receipt_reason": reason, "dashboard": "verified", "macos_codesign": "verified",
            "synthetic_sqlite_and_config": "preserved", "active_app_unchanged": True}


def main():
    require(sys.platform == "darwin", "reopen_trial_macos_required")
    if len(sys.argv) == 4 and sys.argv[1] == "--probe-copy":
        probe_copy(Path(sys.argv[2]), int(sys.argv[3]))
        return
    options = sys.argv[1:]
    require(options in ([], ["--test-fix"], ["--test-fix-rollback"]), "reopen_trial_invalid_arguments")
    fix = None
    if options:
        path = HERE.with_name("build_manager_reopen_fix.py")
        spec = importlib.util.spec_from_file_location("build_manager_reopen_fix", path)
        fix = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fix)
    with tempfile.TemporaryDirectory(prefix="rapbrain-reopen-") as folder:
        print(json.dumps(run_trial(Path.home().resolve(), Path(folder).resolve(), fix,
                                   fail_health=options == ["--test-fix-rollback"])), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        detail = str(error)
        print(json.dumps({"status": "failed", "reason": detail if re.fullmatch(
            r"[a-zA-Z0-9_]+", detail) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
