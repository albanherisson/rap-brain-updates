#!/usr/bin/env python3
"""Upgrade the installed bridge with the reviewed remote Manager startup action."""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time


BRIDGE = "mac_bridge.py"
ADAPTER = "mac_manager_install_request.py"
STARTUP = "mac_manager_start_request.py"
INSTALLER = "mac_install_agent.py"
INSTALLER_SHA = "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"
INSTALLED = {
    BRIDGE: "d148dccbede14e7b4a77ebefc1cfa460878a622d53965dab9830af0bcd698c92",
    ADAPTER: "900650abead9d019c2358d41076b5196f0dbe5f687583180c906b59b7da2ef97",
    STARTUP: "deabf5ecf084c186e8fa5184b2111b379866553ae76a3cc9d4d352c7802540f5",
}
INCOMING = {
    ADAPTER: "4db7de0efb15f7cae34d6312ac00688e0caa7358661529115ccb50c50279c2bf",
    STARTUP: "89ed14eb8f72ec6e32f94b082dfd9f7a8a80ecd100dafcef7e653a3d05bef6a4",
}


def checked(path, expected):
    if path.resolve() != path or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Fichier inattendu : " + path.name)


def main():
    if sys.platform != "darwin" or len(sys.argv) != 1:
        raise ValueError("Activation réservée au Mac de Rap Brain.")
    home = Path.home().resolve()
    source = Path(__file__).resolve().parent
    target = home / "Library/Application Support/RapBrainRemoteBridge"
    for name, expected in INCOMING.items():
        checked(source / name, expected)
    checked(source / INSTALLER, INSTALLER_SHA)
    sys.path[0:0] = [str(source), str(target)]

    from mac_install_agent import upgrade_manager_bridge
    from mac_manager_start_request import parse_start_task

    if not callable(parse_start_task):
        raise ValueError("Le module de démarrage est indisponible.")
    for name, expected in (INSTALLED | INCOMING).items():
        try:
            checked(target / name, expected)
        except ValueError:
            label = upgrade_manager_bridge(home, source, subprocess.run, INSTALLED, INCOMING)
            break
    else:
        label = "com.gns.rapbrain.remote.p0"
    for name, expected in INCOMING.items():
        checked(target / name, expected)

    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        result = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=5)
        if result.returncode == 0 and re.search(r"^\s*state = running\s*$", result.stdout, re.MULTILINE):
            print("Démarrage distant de Rap Brain activé.")
            return
        time.sleep(0.5)
    raise ValueError("La relance de l’agent n’a pas été confirmée.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
