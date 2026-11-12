#!/usr/bin/env python3
"""Install the verified Manager launch retries in the existing Mac bridge."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

INSTALLER_URL = ("https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
                 "fac9dd48ebae97faf0e347573d30a7f73d691cd8/remote-development/mac_install_agent.py")
INSTALLER_SHA = "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"
BRIDGE = Path("Library/Application Support/RapBrainRemoteBridge")
BASELINE = {
    "mac_manager_install_request.py": "9a3414c93c6961c3091fb3cf8ffd66eec736fd04de41e9d0af57848b7129c87e",
    "mac_bridge.py": "40e18003024eede363b83124f0dc2b1803b5bf75b6402b5a24dc1cd3e89ff3a6",
    "mac_manager_sign_request.py": "ce73a414987c902bb181aecc55a697e17bc4fc68d5f1635b682d66b33d0529c5",
    "mac_manager_inventory.py": "a28ab8cd06b7222377e0a08bc22b85d63ea49f71b4a397330db65d5bf3d5b47e",
    "mac_manager_lab_trial.py": "6f82e1074636c39421791f1ca61bfd844a82af1db7e44753b402f227a6e42c79",
    "mac_preflight.py": "ab32901dc7484ecafeab1d54985119763eb07e00d1e2e9a5e1c4ef51b719546b",
    "mac_private_source_trial.py": "907551daea2195a3e470516999706d3ac4ea68216f787b6b214ef9d39dc72bb0",
    "mac_reviewed_test_trial.py": "644e1c99cea699164cccb6a272bb70c502ec15ff78c515869e4026d8771db414",
    "manager_remote_request.py": "bef588df37337ad220d4916057f9c02cd2a5e971ab8f7018a8bda95010031d31",
}

ADAPTER = "mac_manager_install_request.py"
NEW_SHA = "ec411f60d61f017c6708a413911a2143a7ef2a42a51c2ca5cd9358b144fb5431"

def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(path, expected):
    require(path.resolve() == path and path.is_file() and 0 < path.stat().st_size <= 65_536,
            "manager_launch_bridge_file_unsafe")
    raw = path.read_bytes()
    require(sha(raw) in expected, "manager_launch_bridge_baseline_changed")
    return raw


def stage(home, directory, sources):
    bridge = home / BRIDGE
    require(bridge.resolve() == bridge and bridge.is_dir(), "manager_launch_bridge_directory_unsafe")
    for name, expected in BASELINE.items():
        allowed = (expected, NEW_SHA) if name == ADAPTER else (expected,)
        current = checked(bridge / name, allowed)
        if name == ADAPTER:
            before = sha(current)
            current = checked(sources / name, (NEW_SHA,))
        (directory / name).write_bytes(current)
    with urllib.request.urlopen(INSTALLER_URL, timeout=30) as response:
        raw = response.read(65_537)
        require(response.geturl() == INSTALLER_URL and len(raw) <= 65_536 and sha(raw) == INSTALLER_SHA,
                "manager_launch_bridge_installer_changed")
    (directory / "mac_install_agent.py").write_bytes(raw)
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


def activate(home, directory, sources):
    before = stage(home, directory, sources)
    # Import all staged bridge dependencies before stopping the installed agent.
    sys.path.insert(0, str(directory))
    from mac_install_agent import LABEL, upgrade_manager_bridge
    from mac_manager_inventory import running
    from manager_remote_request import REMOTE_TERMINAL, lock_remote_directory, read_remote_json
    from manager_remote_request import remote_directory, remote_receipt

    mailbox = remote_directory(home, create=True)
    fd = lock_remote_directory(mailbox)
    try:
        request = read_remote_json(mailbox / "request.json")
        if request is not None:
            current = remote_receipt(mailbox, request)
            require(current is not None and current.get("state") in REMOTE_TERMINAL,
                    "manager_launch_remote_request_pending")
        if before != NEW_SHA:
            upgrade_manager_bridge(home, directory, subprocess.run, BASELINE, {ADAPTER: NEW_SHA})
    finally:
        os.close(fd)
    for name, expected in (BASELINE | {ADAPTER: NEW_SHA}).items():
        checked(home / BRIDGE / name, (expected,))
    require(wait_for_agent(LABEL), "manager_launch_bridge_not_running")
    try:
        observed = running(home)
        closed = not (observed["beta14_bundle_running"] or observed["applications_bundle_running"])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        closed = None
    return {"status": "pass", "launch_retry": "activated", "launch_agent": "running",
            "manager_closed": closed}


def main():
    require(sys.platform == "darwin" and len(sys.argv) == 1, "manager_launch_macos_required")
    sources = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="rapbrain-activate-launch-") as directory:
        result = activate(Path.home().resolve(), Path(directory).resolve(), sources)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        reason = str(error)
        print(json.dumps({"status": "failed", "reason": reason if re.fullmatch(
            r"[a-zA-Z0-9_]{1,100}", reason) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
