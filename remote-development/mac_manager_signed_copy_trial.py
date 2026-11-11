#!/usr/bin/env python3
"""Exercise the existing signed Manager updater on temporary copies of Beta 14."""

import base64
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import re
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
SERVER_SHA = "4cdab9087a33855e79e8fee5d639cae3489fc7a4399cdc6e0099b15ad8a7e16c"
LAUNCHER_SHA = "dac886a0f3a311b8067c5d9a44a438fc19f6c4eb1ceb69b7c4ffd3dabf9b12ac"
NATIVE_SHA = "00192215cb65a7844555e63d0178f456f3fd8748cbe9c3564bab1380341c1bad"
DASHBOARD_SHA = "9eb2df0a59f5e7638de6251808ea2f64d4a9051d5c169972f3a698b858b4e3a2"
MEMBER = "app/dashboard_beta14.html"
BADGE = b'<span class="versionpill">Beta 14</span>'
TRIAL_BADGE = b'<span class="versionpill">Beta 14 - Essai P0</span>'
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


def fetch_helper():
    with urllib.request.urlopen(HELPER_URL, timeout=20) as response:
        require(response.geturl() == HELPER_URL, "helper_download_redirected")
        outer = response.read(200001)
    require(len(outer) <= 200000, "helper_download_size")
    with zipfile.ZipFile(io.BytesIO(outer)) as archive:
        require(archive.getinfo("helper.zip").file_size <= 150000, "helper_zip_size")
        return archive.read("helper.zip")


def stage_helper(raw, folder):
    require(digest(raw) == HELPER_SHA, "helper_zip_sha256")
    folder.mkdir(mode=0o700)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for entry in archive.infolist():
            require(re.fullmatch(r"helper/[A-Za-z_][A-Za-z_0-9]*\.(py|swift)", entry.filename)
                    and 0 < entry.file_size <= 250000, "helper_zip_layout")
            path = folder / entry.filename.split("/")[1]
            with path.open("xb") as target:
                target.write(archive.read(entry))


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
            "production_key_used": False}


def main():
    require(sys.platform == "darwin", "macos_required")
    helper = fetch_helper()
    with tempfile.TemporaryDirectory(prefix="rapbrain-manager-copy-") as temporary:
        root = Path(temporary).resolve()
        stage_helper(helper, root / "helper")
        sys.path.insert(0, str(root / "helper"))
        result = run_trial(Path.home().resolve(), root)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        message = str(error)
        detail = message if re.fullmatch(r"[a-z0-9_]+", message) else type(error).__name__
        print(json.dumps({"status": "failed", "reason": detail}), file=sys.stderr)
        raise SystemExit(2)
