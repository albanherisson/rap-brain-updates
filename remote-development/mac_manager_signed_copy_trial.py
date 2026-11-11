#!/usr/bin/env python3
"""Exercise the existing signed Manager updater on temporary copies of Beta 14."""

import base64
from contextlib import closing
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


REPO = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
HELPER_URL = REPO + "39a5718e93d3f9520b4cdeab105cdf7e3f332161/manager-postcommit/repair-3.zip"
HELPER_SHA = "378a0f7346814bdff0c885b6748ef6ab8655091d718331eb649a2233a5cda11b"
BACKUP_URL = (REPO + "15638ef4c6c93f266c208e6ed9d20049b14d7a36"
              "/manager-updater/locale_v4/app_bundle_backup.py")
BACKUP_SHA = "54a557d0f90fd74e1d832be12e27a980ae754e2160c5e0e0c5eb3122aed23fd2"
SERVER_SHA = "4cdab9087a33855e79e8fee5d639cae3489fc7a4399cdc6e0099b15ad8a7e16c"
LAUNCHER_SHA = "dac886a0f3a311b8067c5d9a44a438fc19f6c4eb1ceb69b7c4ffd3dabf9b12ac"
NATIVE_SHA = "00192215cb65a7844555e63d0178f456f3fd8748cbe9c3564bab1380341c1bad"
DASHBOARD_SHA = "9eb2df0a59f5e7638de6251808ea2f64d4a9051d5c169972f3a698b858b4e3a2"
MEMBER = "app/dashboard_beta14.html"
BADGE = b'<span class="versionpill">Beta 14</span>'
TRIAL_BADGE = b'<span class="versionpill">Beta 14 - Essai P0</span>'
RUNTIME_SOURCES = {
    "server.py": SERVER_SHA,
    "creative_engine.py": "b770bdf034caa600f75497325f80759d4f372258fa0e911e28f29d214abe85f3",
    "creative_rag.py": "d43f521c43658fce6b3a7de0463efc3fe4d783c6e02b74a5ccd8266a7d35bfca",
    "rhyme_validator.py": "e04be3025b47035e68bfe613798a669c0890cdd402299effb51101fb4578be72",
}
SWIFT_SIGN = """
import CryptoKit
import Foundation
let key = Curve25519.Signing.PrivateKey()
let message = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
print(key.publicKey.rawRepresentation.base64EncodedString())
print(try key.signature(for: message).base64EncodedString())
"""


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, error):
    if not condition:
        raise ValueError(error)


def run_checked(args, error, timeout=90):
    result = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                            timeout=timeout)
    require(result.returncode == 0, error)
    return result.stdout


def fetch_bytes(url, limit):
    with urllib.request.urlopen(url, timeout=20) as response:
        require(response.geturl() == url, "download_redirected")
        raw = response.read(limit + 1)
    require(0 < len(raw) <= limit, "download_size")
    return raw


def fetch_helper():
    outer = fetch_bytes(HELPER_URL, 200000)
    with zipfile.ZipFile(io.BytesIO(outer)) as archive:
        require(archive.getinfo("helper.zip").file_size <= 150000, "helper_zip_size")
        return archive.read("helper.zip")


def stage_helper(raw, backup, folder):
    require(digest(raw) == HELPER_SHA, "helper_zip_sha256")
    require(digest(backup) == BACKUP_SHA, "backup_reader_sha256")
    folder.mkdir(mode=0o700)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for entry in archive.infolist():
            require(re.fullmatch(r"helper/[A-Za-z_][A-Za-z_0-9]*\.(py|swift)", entry.filename)
                    and 0 < entry.file_size <= 250000, "helper_zip_layout")
            path = folder / entry.filename.split("/")[1]
            # Reuse the locale repair's exact Finder icon support in this trial.
            contents = backup if path.name == "app_bundle_backup.py" else archive.read(entry)
            with path.open("xb") as target:
                target.write(contents)


def sign_ephemeral(message, folder):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    except ModuleNotFoundError:
        path = folder / "test-message.json"
        path.write_bytes(message)
        output = run_checked(["/usr/bin/swift", "-e", SWIFT_SIGN, str(path)],
                             "test_key_sign_failed", timeout=120)
        public, signature = (base64.b64decode(line, validate=True)
                             for line in output.splitlines())
    else:
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        signature = key.sign(message)
    require(len(public) == 32 and len(signature) == 64, "test_key_invalid")
    return public, signature


def signed_trial(dashboard, folder):
    from bootstrap_release import PUBLISHER_PIN
    from creative_release import canonical

    require(digest(dashboard) == DASHBOARD_SHA and dashboard.count(BADGE) == 1
            and b'onclick="installManagerUpdate()"' in dashboard, "dashboard_baseline_changed")
    payload = dashboard.replace(BADGE, TRIAL_BADGE, 1)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(MEMBER, payload)
    archive = stream.getvalue()
    now = int(time.time())
    # Match the real verifier's schema in memory with an isolated trust key.
    # The production Manager rejects this envelope at its publisher check.
    manifest = {
        "schema": "rapbrain-manager-production-v1",
        "sequence": 14,
        "issued_at": now - 1,
        "expires_at": now + 3600,
        "production_install_authorized": True,
        "data_migrations": [],
        "validation": {"macos_copy_install": "passed", "rollback": "passed", "runtime": "passed"},
        "files": [{"path": MEMBER, "baseline_sha256": DASHBOARD_SHA,
                   "payload_sha256": digest(payload)}],
        "required_server_sha256": SERVER_SHA,
        "archive_url": REPO + "main/manager-stable/p0-copy-trial.zip",
        "archive_sha256": digest(archive),
        "archive_bytes": len(archive),
    }
    public, signature = sign_ephemeral(canonical(manifest), folder)
    pin = digest(public)
    require(pin != PUBLISHER_PIN, "test_key_matches_production")
    signed = canonical({"signed_payload": manifest, "signature_algorithm": "Ed25519",
                        "public_key_base64": base64.b64encode(public).decode("ascii"),
                        "signature_base64": base64.b64encode(signature).decode("ascii")})
    return signed, archive, payload, pin


def seed_data(source):
    data = source / "data"
    data.mkdir(mode=0o700)
    (data / "ollama_model.json").write_bytes(b'{"model":"p0-fixture"}\n')
    (data / "library-fixture.txt").write_bytes(b"P0 synthetic library\n")
    with closing(sqlite3.connect(data / "rapbrain.sqlite3")) as db, db:
        db.execute("CREATE TABLE jobs (status TEXT)")
        db.execute("INSERT INTO jobs VALUES ('done')")
        db.execute("CREATE TABLE analyses (body TEXT)")
        db.execute("INSERT INTO analyses VALUES ('P0 synthetic analysis')")
    return data


def data_snapshot(data):
    return {path.name: digest(path.read_bytes()) for path in data.iterdir()}


def run_trial(home, root):
    from app_bundle_backup import _copy_verified, inventory
    from creative_release import Refused
    from creative_transaction import safe_path
    from manager_offline_lifecycle import MacOfflineManagerLifecycle
    from manager_update_release import verify_manifest
    from manager_update_transaction import ManagerUpdateTransaction

    app = safe_path(home / "Downloads" / "RapBrainManager_App_Beta14"
                    / "Rap Brain Manager Beta 14.app", directory=True)
    resources = app / "Contents" / "Resources"
    server_file = safe_path(home / "Downloads" / "rap-brain" / "server.py")
    server = server_file.read_bytes()
    require(digest(server) == SERVER_SHA, "server_baseline_changed")
    require(digest(safe_path(resources / "launch_manager.py").read_bytes()) == LAUNCHER_SHA,
            "launcher_baseline_changed")
    require(digest(safe_path(resources / "RapBrainManagerNative.swift").read_bytes()) == NATIVE_SHA,
            "native_baseline_changed")
    dashboard = safe_path(resources / "dashboard_beta14.html").read_bytes()
    original_app = inventory(app)
    signed, archive, payload, pin = signed_trial(dashboard, root)
    try:
        verify_manifest(signed)
    except Refused as exc:
        require(str(exc) == "manager_publisher_mismatch", "test_release_rejection_unexpected")
    else:
        raise ValueError("test_release_accepted_by_production")

    for expected, stage in (("committed", "installation"), ("rolled_back", "retour arrière")):
        print("Essai sur copie : " + stage, flush=True)
        branch = root / expected
        branch.mkdir(mode=0o700)
        copy_app = branch / "Manager.app"
        _copy_verified(app, copy_app, original_app)
        run_checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(copy_app)],
                    "original_copy_signature_invalid")
        copy_resources = copy_app / "Contents" / "Resources"
        source = branch / "rap-brain"
        source.mkdir(mode=0o700)
        (source / "server.py").write_bytes(server)
        (source / "creative_engine.py").write_bytes(b"# P0 copy trial\n")
        data = seed_data(source)
        before_data = data_snapshot(data)
        state = branch / "secure-update"
        state.mkdir(mode=0o700)
        health_checks = []

        def inspect_copy(copy_source, inspected_resources):
            require(copy_source == source and inspected_resources.is_relative_to(branch),
                    "copy_inspection_escaped")
            return {"server_process_seen": False, "manager_process_seen": False,
                    "port_8765_listening": False}

        class CopyLifecycle(MacOfflineManagerLifecycle):
            def start_and_check(self):
                self._sign()
                code_state = self._code_state()
                health_checks.append(code_state)
                return expected == "committed" or code_state == "baseline"

        launcher = copy_resources / "launch_manager.py"
        lifecycle = CopyLifecycle(source, launcher, state, signed, pinned_key=pin,
                                  inspector=inspect_copy)
        result = ManagerUpdateTransaction(source, launcher, state, lifecycle,
                                          pinned_key=pin).install(signed, archive)
        require(result.get("state") == expected, "unexpected_transaction_result")
        require(health_checks == (["candidate"] if expected == "committed"
                                  else ["candidate", "baseline"]), "health_scenario_changed")
        require(not (state / "maintenance.ticket").exists(), "copy_maintenance_ticket_left")
        require(data_snapshot(data) == before_data, "synthetic_data_changed")
        require(digest((source / "server.py").read_bytes()) == SERVER_SHA, "copy_server_changed")
        installed_dashboard = (copy_resources / "dashboard_beta14.html").read_bytes()
        require(installed_dashboard == (payload if expected == "committed" else dashboard),
                "unexpected_dashboard_bytes")
        if expected == "rolled_back":
            require(inventory(copy_app) == original_app, "app_rollback_changed")
        run_checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(copy_app)],
                    "final_copy_signature_invalid")
    require(inventory(app) == original_app and digest(server_file.read_bytes()) == SERVER_SHA,
            "active_code_changed")
    return {"status": "pass", "copy_install": "committed", "copy_rollback": "rolled_back",
            "macos_codesign": "verified", "health_failure": "simulated",
            "synthetic_data_preserved": True, "active_code_unchanged": True,
            "finder_icon_present_and_preserved": "Icon\r" in original_app,
            "production_key_used": False}


def local_json(port, method, path, *, body=None, headers=None):
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=4)) as connection:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read(4097)
        require(len(raw) <= 4096, "runtime_response_oversize")
        return response.status, json.loads(raw)


def wait_for_runtime(process, port, token):
    from authenticated_runtime_client import read_runtime_proof
    from creative_release import Refused

    last_error = "runtime_not_ready"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        require(process.poll() is None, "runtime_exited_before_ready")
        try:
            return read_runtime_proof(port, token, expected_parent_pid=process.pid)
        except Refused as error:
            last_error = str(error)
            time.sleep(0.2)
    raise ValueError(last_error)


def signal_trial_group(process, signal_number):
    # Popen starts a new session for this exact copy and its worker.
    try:
        os.killpg(process.pid, signal_number)
    except ProcessLookupError:
        return False
    return True


def exercise_runtime(source, workspace):
    from authenticated_runtime_client import assert_owned_listener

    data = workspace / "data"
    state = workspace / "Downloads/RapBrainManagerBackups/secure-update"
    state.mkdir(mode=0o700, parents=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as address:
        address.bind(("127.0.0.1", 0))
        port = address.getsockname()[1]
    require(port not in (8765, 11434), "runtime_port_not_isolated")
    token = secrets.token_hex(32)
    env = {"HOME": str(workspace), "TMPDIR": str(workspace), "PATH": "/usr/bin:/bin",
           "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "RAP_BRAIN_DATA": str(data), "RAP_BRAIN_PORT": str(port),
           "OLLAMA_URL": "http://127.0.0.1:1", "RB_UPDATE_PROBE_TOKEN": token}
    with (workspace / "server-output.log").open("xb") as log:
        process = subprocess.Popen([sys.executable, "-s", "-B", str(source / "server.py")],
                                   cwd=source, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        completed = False
        try:
            print("Essai serveur : démarrage et contrôle de santé", flush=True)
            proof = wait_for_runtime(process, port, token)
            require(os.getpgid(proof["worker_pid"]) == process.pid, "runtime_worker_group_mismatch")
            require(local_json(port, "GET", "/api/health")
                    == (200, {"ok": True, "worker": "separate_process"}), "runtime_health_failed")
            require(local_json(port, "GET", "/api/manager-update-proof")
                    == (404, {"error": "not_found"}), "runtime_proof_unprotected")

            track = {"artist": "Rap Brain P0", "title": "Temporary runtime trial",
                     "lyrics": "Synthetic test text"}
            assert_owned_listener(port, process.pid)
            status, saved = local_json(port, "POST", "/api/tracks", body=json.dumps(track),
                                       headers={"Content-Type": "application/json"})
            require(status in (200, 201) and type(saved) is dict
                    and type(saved.get("id")) is int and saved["id"] > 0, "runtime_track_write_failed")
            status, found = local_json(port, "GET", f"/api/tracks/{saved['id']}")
            require(status == 200 and all(found.get("track", {}).get(key) == value
                    for key, value in track.items()), "runtime_track_read_failed")

            print("Essai serveur : arrêt authentifié", flush=True)
            ticket = secrets.token_hex(32)
            marker = state / "maintenance.ticket"
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                stream.write(ticket + "\n")
            assert_owned_listener(port, process.pid)
            require(local_json(port, "POST", "/api/manager-update-stop", headers={
                "X-RB-Update-Token": token, "X-RB-Update-Ticket": ticket,
            }) == (202, {"stopping": True}), "runtime_shutdown_refused")
            require(process.wait(timeout=12) == 0, "runtime_shutdown_exit_failed")
            deadline = time.monotonic() + 3
            while signal_trial_group(process, 0):
                require(time.monotonic() < deadline, "runtime_worker_still_running")
                time.sleep(0.1)
            completed = True
        finally:
            if not completed:
                signal_trial_group(process, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    signal_trial_group(process, signal.SIGKILL)
                    process.wait(timeout=3)
                if signal_trial_group(process, 0):
                    signal_trial_group(process, signal.SIGKILL)

    db_path = data / "rapbrain.sqlite3"
    require(db_path.is_file() and not db_path.is_symlink(), "runtime_database_missing")
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
        require(db.execute("PRAGMA quick_check").fetchall() == [("ok",)], "runtime_database_integrity")
        require(db.execute("SELECT artist, title, lyrics FROM tracks").fetchall()
                == [(track["artist"], track["title"], track["lyrics"])], "runtime_database_content")


def run_runtime_trial(home, root):
    from creative_transaction import safe_path

    installed = safe_path(home / "Downloads" / "rap-brain", directory=True)
    workspace = root / "runtime"
    source = workspace / "source"
    source.mkdir(mode=0o700, parents=True)
    for name, expected in RUNTIME_SOURCES.items():
        raw = safe_path(installed / name).read_bytes()
        require(digest(raw) == expected, "runtime_source_changed_" + name.removesuffix(".py"))
        (source / name).write_bytes(raw)
    exercise_runtime(source, workspace)
    require(all(digest(safe_path(installed / name).read_bytes()) == expected
                for name, expected in RUNTIME_SOURCES.items()), "active_code_changed")
    return {"status": "pass", "server_health": "verified", "worker_identity": "verified",
            "synthetic_sqlite": "verified", "graceful_shutdown": "verified",
            "active_sources_unchanged": True, "production_port_used": False}


def main():
    require(sys.platform == "darwin", "macos_required")
    require(sys.argv[1:] in ([], ["--runtime"]), "invalid_trial_option")
    trial = run_runtime_trial if sys.argv[1:] else run_trial
    helper = fetch_helper()
    backup = fetch_bytes(BACKUP_URL, 20000)
    with tempfile.TemporaryDirectory(prefix="rapbrain-manager-copy-") as temporary:
        root = Path(temporary).resolve()
        stage_helper(helper, backup, root / "helper")
        sys.path.insert(0, str(root / "helper"))
        result = trial(Path.home().resolve(), root)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, http.client.HTTPException,
            sqlite3.Error, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        message = str(error)
        detail = message if re.fullmatch(r"[a-z0-9_]+", message) else type(error).__name__
        print(json.dumps({"status": "failed", "reason": detail}), file=sys.stderr)
        raise SystemExit(2)
