#!/usr/bin/env python3
"""Activate signed restart support on the existing Rap Brain bridge."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

LABEL = "com.gns.rapbrain.remote.p0"
ADAPTER = "mac_manager_install_request.py"
HELPER = "mac_signed_server_restart.py"
INSTALLER = "mac_install_agent.py"
INSTALLER_SHA = "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"
PREVIOUS = "ec411f60d61f017c6708a413911a2143a7ef2a42a51c2ca5cd9358b144fb5431"
INCOMING = {
    ADAPTER: "900650abead9d019c2358d41076b5196f0dbe5f687583180c906b59b7da2ef97",
    HELPER: "12bbfd8ed4e67107a4f5caf8ee88a1c1d82647a73679f7bc11a9df66e6eae97c",
}
DEPENDENCIES = {
    "mac_bridge.py": "4c510dc3a6494867f06cbe21dd8cd5c2682817b6634179a4f25d1986a512e207",
    "mac_manager_sign_request.py": "9e6c29deeba7697c78c6ffe578e14f81a4e1da63d195f117e21e78fd582ef3dc",
    "mac_private_source_trial.py": "907551daea2195a3e470516999706d3ac4ea68216f787b6b214ef9d39dc72bb0",
    "manager_remote_request.py": "bef588df37337ad220d4916057f9c02cd2a5e971ab8f7018a8bda95010031d31",
}


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Fichier du pont absent ou remplacé.")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if sys.platform != "darwin" or len(sys.argv) != 1:
        raise ValueError("Activation réservée au Mac de RAP BRAIN.")
    home = Path.home().resolve()
    installed = home / "Library/Application Support/RapBrainRemoteBridge"
    source = Path(__file__).resolve().parent
    if (installed.resolve() != installed or digest(source / INSTALLER) != INSTALLER_SHA
            or any(digest(source / name) != expected for name, expected in INCOMING.items())):
        raise ValueError("Fichiers de l’activation inattendus.")
    if any(digest(installed / name) != expected for name, expected in DEPENDENCIES.items()):
        raise ValueError("Version installée du pont inattendue.")

    sys.path.insert(0, str(installed))
    from mac_manager_sign_request import verified_helpers
    with tempfile.TemporaryDirectory(prefix="rapbrain-bridge-check-") as directory:
        verified_helpers(home, Path(directory).resolve())

    sys.path.insert(0, str(source))
    from mac_install_agent import upgrade_manager_bridge
    upgrade_manager_bridge(home, source, subprocess.run, DEPENDENCIES | {ADAPTER: PREVIOUS},
                           {ADAPTER: INCOMING[ADAPTER]}, additions={HELPER: INCOMING[HELPER]})
    if any(digest(installed / name) != expected for name, expected in INCOMING.items()):
        raise ValueError("Empreinte du pont non confirmée.")
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        state = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=5)
        if state.returncode == 0 and re.search(r"^\s*state = running\s*$", state.stdout, re.MULTILINE):
            print(json.dumps({"status": "pass", "signed_restart": "activated"}))
            return
        time.sleep(0.5)
    raise ValueError("Le pont n’a pas confirmé sa relance.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc)) from None
