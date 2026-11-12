#!/usr/bin/env python3
"""Sign and rehearse the Manager repair without applying it to the owner Mac."""

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

RAW = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
FIX = RAW + "a7e3974ba72f952d6f003e8f5b37e73db5bdbbd3/remote-development/"
OLD = RAW + "c73c4b318f468eb077b3f013556ffa7368d804ba/manager-updater/"
BRIDGE = RAW + "fac9dd48ebae97faf0e347573d30a7f73d691cd8/remote-development/"
STABLE = RAW + "bfce88ae32cb18967a59c0bfbe683349ac85310b/manager-stable/"
REVIEWED_REPAIR = RAW + "d3c4950b046c66fe6b67940ffbcfab1e3796480d/remote-development/reopen-release/"
REPAIR_PINS = {
    "build_manager_repair_app.py": "f4fa333144d40311e4cfa2879f43ffd81173e5e733d714b3deebd1b8fc6b08b3",
    "mac_manager_install_request.py": "519dae5e5bfe2de40b700f668d0a55344da60ec72cd6dfda6586addcfbb1767c",
    "manager_repair_installer.py": "bc174ed3ac6446b55be7914f84d188eded9192dc02496c77cdfff19e237e4680",
    "manager_repair_rehearsal.py": "07adb8440936f956a21aff110d451298db49f61166c1147e35eef41bfb4ebeed",
    "manager_repair_release.py": "7dfaa1a40313f0057aa0666a52998c31516218660d42f203c6b926e80a79aa5d",
    "manager_repair_transaction.py": "e2146f4a63014a00c2dc603748d1f49ac127000b5f520da955369d3bfa3b60cb",
}
HELPER_TREE = "a1e605d0fbbbe0598f4aee49f3bd2b5f7325dc2eb2bffcc8802e56e57a36ae9e"
APP = Path("Downloads/RapBrainManager_App_Beta14/Rap Brain Manager Beta 14.app")
STATE = Path("Downloads/RapBrainManagerBackups/secure-update")
SOURCE = Path("Downloads/rap-brain")
APP_NAME = "Réparer la mise à jour du Manager.app"
ZIP_NAME = "RapBrain_Manager_Reopen_16_Signed.zip"
OUTPUT_DIR = "RapBrain_Manager_Reopen_16"
DASHBOARD = "cd698665767d379c312ada30cdcbebf0157fba6bda1f3aa501bb982d41872259"
SUPPORT = {
    OLD: {
        "build_first_bootstrap_app.py": "8984e24ae987873063284e091a4ba821623019df224616487116632bd14eb0a4",
        "mac_sign_manager_capability.py": "7d881007d101b6648968734fda9f64c4e0475d18c2331aa5142e33d384d112d9",
        "manager_helper_inventory.py": "b9616d39105a9ea45cf616def56ff965023840e642ca5f54f0d9f297b9eb39a5",
        "manager_helper_release.py": "ee4c6281094c3289fc7329e1415d0a69f3acaa0d14a6fc86fdecb27b1cb8c57a",
        "python_bootstrap_selector.sh": "09a03c8e6e3f3d3c4674acd76aeb5a242bbc1e9070da62fb0041618ecc27de07",
    },
    FIX: {"build_manager_reopen_fix.py": "11878c4defef7ea8e8f78aad64d5e05c565ee85f43cf7fcec460062cce072605"},
    BRIDGE: {
        "mac_bridge.py": "0567ee64b6c809c09821b858ab79a637749b2f316f05548f66543acac3eae01e",
        "mac_install_agent.py": "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8",
        "mac_manager_inventory.py": "a28ab8cd06b7222377e0a08bc22b85d63ea49f71b4a397330db65d5bf3d5b47e",
        "mac_manager_lab_trial.py": "6f82e1074636c39421791f1ca61bfd844a82af1db7e44753b402f227a6e42c79",
        "mac_preflight.py": "ab32901dc7484ecafeab1d54985119763eb07e00d1e2e9a5e1c4ef51b719546b",
        "mac_private_source_trial.py": "907551daea2195a3e470516999706d3ac4ea68216f787b6b214ef9d39dc72bb0",
        "mac_reviewed_test_trial.py": "644e1c99cea699164cccb6a272bb70c502ec15ff78c515869e4026d8771db414",
        "manager_remote_request.py": "bef588df37337ad220d4916057f9c02cd2a5e971ab8f7018a8bda95010031d31",
    },
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def fetch(url, expected, limit=250_000):
    require(url.startswith(RAW), "reopen_release_origin_invalid")
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read(limit + 1)
        require(response.geturl() == url and 0 < len(raw) <= limit and sha(raw) == expected,
                "reopen_release_dependency_changed")
    return raw


def packed(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, raw in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | 0o600) << 16
            package.writestr(entry, raw)
    return stream.getvalue()


def read_helper(directory):
    require(directory.resolve() == directory and directory.is_dir(), "reopen_release_helper_path")
    members = {}
    for path in sorted(directory.iterdir()):
        if path.name == "signed-manifest.json":
            continue
        require(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*\.(py|swift)", path.name)
                and not path.is_symlink() and path.is_file() and 0 < path.stat().st_size <= 250_000,
                "reopen_release_helper_member")
        members[path.name] = path.read_bytes()
    fingerprint = sha("".join(f"{name} {sha(raw)}\n" for name, raw in members.items()).encode())
    require(fingerprint == HELPER_TREE, "reopen_release_helper_tree_changed")
    return members


def stage_dependencies(root, state, download=fetch):
    members = read_helper(state / "helper")
    for name, raw in members.items():
        (root / name).write_bytes(raw)
    for base, pins in (*SUPPORT.items(), (REVIEWED_REPAIR, REPAIR_PINS)):
        for name, expected in pins.items():
            (root / name).write_bytes(download(base + name, expected))
    sys.path.insert(0, str(root))
    return members


def compose(home, root, sign, *, download=fetch):
    state = home / STATE
    members = stage_dependencies(root, state, download)
    from build_manager_reopen_fix import build_helpers, build_launcher
    from creative_transaction import safe_path
    from manager_helper_release import verify_staged
    from manager_repair_installer import bridge_baseline
    from manager_repair_release import (ARCHIVE, BRIDGE_ADAPTER, CORRECTED_LAUNCHER,
        LAUNCHER, NATIVE_SOURCE, SEQUENCE, SERVER, verify_release)
    from manager_update_release import verify_archive, verify_manifest
    from pending_attempt_recovery import _private_json
    from strict_json import parse_signed_json

    app = safe_path(home / APP, directory=True)
    resources = app / "Contents/Resources"
    launcher = safe_path(resources / "launch_manager.py")
    native = safe_path(resources / "RapBrainManagerNative.swift").read_bytes()
    source = safe_path(home / SOURCE, directory=True)
    for raw, expected in ((launcher.read_bytes(), LAUNCHER), (native, NATIVE_SOURCE),
                          (safe_path(source / "server.py").read_bytes(), SERVER),
                          (safe_path(resources / "dashboard_beta14.html").read_bytes(), DASHBOARD)):
        require(sha(raw) == expected, "reopen_release_active_baseline_changed")
    require(_private_json(state / "manager-accepted.json", 256) == {"sequence": 14},
            "reopen_release_accepted_sequence_changed")
    require(not any(os.path.lexists(state / name) for name in
                ("maintenance.ticket", "bootstrap-intent.json", "maintenance-intent.json",
                 "manager-reopen-repair.json")), "reopen_release_pending_transaction")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                   check=True, capture_output=True, timeout=60)
    installed = verify_staged(state)
    old_helper = parse_signed_json((installed / "signed-manifest.json").read_bytes())["signed_payload"]
    require(old_helper["sequence"] < SEQUENCE and
            old_helper["files"] == {name: sha(raw) for name, raw in members.items()},
            "reopen_release_helper_manifest_changed")
    bridge_baseline(home)

    sequence_15 = download(STABLE + "manifest.json", "525942b65bb77cd9400ccf08eb9761d7746674da509ad46606db2ec6d66f0daa")
    issued = parse_signed_json(sequence_15)["signed_payload"]["issued_at"]
    release_15 = verify_manifest(sequence_15, minimum_sequence=14, now=issued)
    archive_15 = download(STABLE + "update-15.zip", "42f91c69a313b8740be5f013d542148328ceb43d75daf9e1590e810c814d8fa1")
    old_launcher = verify_archive(archive_15, release_15)["app/launch_manager.py"]
    candidate = build_launcher(old_launcher)
    adapter = safe_path(root / "mac_manager_install_request.py").read_bytes()
    require(sha(candidate) == CORRECTED_LAUNCHER and sha(adapter) == BRIDGE_ADAPTER,
            "reopen_release_candidate_hash_changed")

    helper_members = members | build_helpers(root)
    helper_zip = packed({"helper/" + name: raw for name, raw in helper_members.items()})
    files = {"app/launch_manager.py": candidate, "app/RapBrainManagerNative.swift": native,
             "bridge/mac_manager_install_request.py": adapter, "helper.zip": helper_zip}
    archive = packed(files)
    now = int(time.time())
    common = {"sequence": SEQUENCE, "issued_at": now - 1, "expires_at": now + 14 * 86400,
              "production_install_authorized": True,
              "validation": {"macos_copy_install": "passed", "rollback": "passed", "runtime": "passed"}}
    helper_signed = sign(common | {"schema": "rapbrain-manager-helper-v1",
        "files": {name: sha(raw) for name, raw in helper_members.items()},
        "archive_sha256": sha(helper_zip), "archive_bytes": len(helper_zip)})
    signed = sign(common | {"schema": "rapbrain-manager-repair-v1", "data_migrations": [],
        "baseline_launcher_sha256": LAUNCHER, "baseline_native_source_sha256": NATIVE_SOURCE,
        "baseline_helper_sha256": old_helper["archive_sha256"], "required_server_sha256": SERVER,
        "archive_url": ARCHIVE, "archive_sha256": sha(archive), "archive_bytes": len(archive),
        "files": {name: sha(raw) for name, raw in files.items()},
        "helper_manifest_base64": base64.b64encode(helper_signed).decode("ascii")})
    _, verified, _ = verify_release(signed, archive)
    require(verified == files, "reopen_release_verification_failed")
    return source, launcher, state, signed, archive


def sign_with_owner_key(home, payload):
    # Imported after the exact historical signer has been staged.
    from mac_sign_manager_capability import envelope

    key = home / "Library/Application Support/RapBrainManager/publisher_ed25519.key"
    return envelope(payload, key)


def prepare(home, root):
    from functools import partial

    source, launcher, state, signed, archive = compose(
        home, root, partial(sign_with_owner_key, home))
    from build_manager_repair_app import build
    from mac_manager_install_request import compatible_launcher
    from manager_repair_rehearsal import rehearse_on_copy

    def bridge_check(_source, copied_launcher, _state):
        unknown = copied_launcher.with_name("unknown-launcher.py")
        unknown.write_bytes(b"# unknown")
        return compatible_launcher(copied_launcher) and not compatible_launcher(unknown)

    print("Réparation signée 16. Essais d’installation et de retour arrière sur copies.", flush=True)
    report = rehearse_on_copy(source, launcher, state, signed, archive, post_commit=bridge_check)
    require(report == {"state": "passed", "live_database_opened": False,
            "live_configuration_opened": False, "active_files_modified": False},
            "reopen_release_copy_rehearsal_failed")

    export = root / "export"
    export.mkdir(mode=0o700)
    app = export / APP_NAME
    require(build(app, release=signed, archive=archive, source=root)["signature_verified"],
            "reopen_release_finder_signature_failed")
    public = packed({"manager-reopen/manifest.json": signed, "manager-reopen/repair-16.zip": archive})
    destination = home / "Downloads" / OUTPUT_DIR
    fd = os.open(export / ZIP_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(public)
        file.flush()
        os.fsync(file.fileno())
    require(not os.path.lexists(destination), "reopen_release_output_exists")
    os.rename(export, destination)
    return {"status": "pass", "repair_sequence": 16, "copy_install": "committed",
            "copy_rollback": "rolled_back", "bridge_launcher": "recognized_on_copy",
            "publisher_signature": "verified", "finder_codesign": "verified",
            "installation_performed": False, "zip": ZIP_NAME, "zip_sha256": sha(public),
            "installer": APP_NAME, "folder": OUTPUT_DIR}


def main():
    require(sys.platform == "darwin" and len(sys.argv) == 1 and bool(REPAIR_PINS),
            "reopen_release_macos_required")
    home = Path.home().resolve()
    downloads = home / "Downloads"
    require(downloads.is_dir() and downloads.resolve() == downloads
            and not os.path.lexists(downloads / OUTPUT_DIR),
            "reopen_release_output_exists_or_unsafe")
    with tempfile.TemporaryDirectory(prefix="rapbrain-reopen-release-", dir=downloads) as name:
        result = prepare(home, Path(name).resolve())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        reason = str(error)
        print(json.dumps({"status": "failed", "reason": reason if re.fullmatch(
            r"[a-zA-Z0-9_]{1,120}", reason) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
