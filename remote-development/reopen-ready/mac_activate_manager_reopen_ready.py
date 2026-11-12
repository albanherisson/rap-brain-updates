#!/usr/bin/env python3
"""Prove the Manager dashboard on this Mac, then update the known bridge adapter."""

import hashlib
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

INSTALLER_URL = ("https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
                 "fac9dd48ebae97faf0e347573d30a7f73d691cd8/remote-development/mac_install_agent.py")
INSTALLER_SHA = "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"
ADAPTER = "mac_manager_install_request.py"
NEW_SHA = "9ce990a7871aae724d3573101feff4ccde050862effb74922625f85e6cdc2c2c"
BRIDGE = Path("Library/Application Support/RapBrainRemoteBridge")
BASELINE = {
    ADAPTER: "519dae5e5bfe2de40b700f668d0a55344da60ec72cd6dfda6586addcfbb1767c",
    "mac_bridge.py": "0567ee64b6c809c09821b858ab79a637749b2f316f05548f66543acac3eae01e",
    "mac_manager_inventory.py": "a28ab8cd06b7222377e0a08bc22b85d63ea49f71b4a397330db65d5bf3d5b47e",
    "mac_manager_lab_trial.py": "6f82e1074636c39421791f1ca61bfd844a82af1db7e44753b402f227a6e42c79",
    "mac_preflight.py": "ab32901dc7484ecafeab1d54985119763eb07e00d1e2e9a5e1c4ef51b719546b",
    "mac_private_source_trial.py": "907551daea2195a3e470516999706d3ac4ea68216f787b6b214ef9d39dc72bb0",
    "mac_reviewed_test_trial.py": "644e1c99cea699164cccb6a272bb70c502ec15ff78c515869e4026d8771db414",
    "manager_remote_request.py": "bef588df37337ad220d4916057f9c02cd2a5e971ab8f7018a8bda95010031d31",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(path, expected):
    require(path.resolve() == path and path.is_file() and 0 < path.stat().st_size <= 65_536,
            "manager_reopen_bridge_file_unsafe")
    raw = path.read_bytes()
    require(sha(raw) in expected, "manager_reopen_bridge_baseline_changed")
    return raw


def stage(home, directory, adapter):
    bridge = home / BRIDGE
    before = None
    for name, expected in BASELINE.items():
        current = checked(bridge / name, (expected, NEW_SHA) if name == ADAPTER else (expected,))
        if name == ADAPTER:
            before = sha(current)
            current = adapter
        (directory / name).write_bytes(current)
    with urllib.request.urlopen(INSTALLER_URL, timeout=30) as response:
        raw = response.read(65_537)
        require(response.geturl() == INSTALLER_URL and len(raw) <= 65_536 and sha(raw) == INSTALLER_SHA,
                "manager_reopen_bridge_installer_changed")
    (directory / "mac_install_agent.py").write_bytes(raw)
    sys.path.insert(0, str(directory))
    return before


def wait_for_agent(label):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        result = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=5)
        if result.returncode == 0 and re.search(r"^\s*state = running\s*$", result.stdout, re.MULTILINE):
            return True
        time.sleep(0.5)
    return False


def native_log_state(home):
    log = home / "Library/Logs/RapBrainManager-Beta13.log"
    if log.parent.resolve() != log.parent:
        return "unavailable"
    try:
        fd = os.open(log, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                return "unavailable"
            stream.seek(max(0, info.st_size - 32_768))
            data = stream.read(32_768)
    except OSError:
        return "unavailable"
    markers = re.findall(rb"^(?:Tableau de bord :|RC40 REFUSED:|Mise . jour du Manager en cours)",
                         data, re.MULTILINE)
    return {b"Tableau de bord :": "dashboard_announced", b"RC40 REFUSED:": "startup_refused"}.get(
        markers[-1] if markers else b"", "no_dashboard_announcement")


def activate(home, directory, adapter):
    before = stage(home, directory, adapter)
    from mac_install_agent import LABEL, upgrade_manager_bridge
    from mac_manager_install_request import (APP, HANDOFF_RECEIPT, LAUNCHER, compatible_launcher,
        dashboard_ready, reopen_manager)
    from manager_remote_request import REMOTE_TERMINAL, lock_remote_directory, read_remote_json, remote_directory, remote_receipt

    require(compatible_launcher(home / APP / LAUNCHER), "manager_reopen_launcher_changed")
    handoff = home / HANDOFF_RECEIPT
    require(handoff.parent.resolve() == handoff.parent and not any(
        os.path.lexists(handoff.parent / name) for name in
        ("maintenance.ticket", "bootstrap-intent.json", "maintenance-intent.json")),
        "manager_reopen_maintenance_pending")
    receipt = read_remote_json(handoff)
    require(type(receipt) is dict and receipt.get("state") in ("committed", "rolled_back")
            and type(receipt.get("attempt")) is str and re.fullmatch(r"[0-9a-f]{32}", receipt["attempt"]),
            "manager_reopen_handoff_not_found")
    accepted = read_remote_json(handoff.with_name("manager-accepted.json"))
    require(type(accepted) is dict and type(accepted.get("sequence")) is int and accepted["sequence"] > 0,
            "manager_reopen_accepted_sequence_missing")

    print("Vérification du tableau de bord installé sur ce Mac.", flush=True)
    observed = {"dashboard_port_declared": False, "dashboard_process_verified": False,
                "dashboard_http_responded": False}
    def probe(home, attempt, state):
        return dashboard_ready(home, attempt, state, diagnostics=observed)

    if not reopen_manager(home, receipt["attempt"], receipt["state"], probe=probe):
        return {"status": "failed", "reason": "manager_reopen_dashboard_unverified",
                "native_log": native_log_state(home), **observed}

    mailbox = remote_directory(home, create=True)
    fd = lock_remote_directory(mailbox)
    try:
        request = read_remote_json(mailbox / "request.json")
        if request is not None:
            current = remote_receipt(mailbox, request)
            require(current is not None and current.get("state") in REMOTE_TERMINAL,
                    "manager_reopen_remote_request_pending")
        if before != NEW_SHA:
            upgrade_manager_bridge(home, directory, subprocess.run, BASELINE, {ADAPTER: NEW_SHA})
    finally:
        os.close(fd)
    checked(home / BRIDGE / ADAPTER, (NEW_SHA,))
    require(wait_for_agent(LABEL), "manager_reopen_bridge_not_running")
    return {"status": "pass", "sequence": accepted["sequence"], "manager_dashboard": "verified",
            "bridge_adapter": "activated", "launch_agent": "running"}


def main():
    require(sys.platform == "darwin" and len(sys.argv) == 1, "manager_reopen_macos_required")
    adapter = checked(Path(__file__).resolve().with_name(ADAPTER), (NEW_SHA,))
    with tempfile.TemporaryDirectory(prefix="rapbrain-reopen-ready-") as name:
        result = activate(Path.home().resolve(), Path(name).resolve(), adapter)
    print(json.dumps(result, sort_keys=True), flush=True)
    if result["status"] != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        reason = str(error)
        print(json.dumps({"status": "failed", "reason": reason if re.fullmatch(
            r"[a-zA-Z0-9_]{1,100}", reason) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
