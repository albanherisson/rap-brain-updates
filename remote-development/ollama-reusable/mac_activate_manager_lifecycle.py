#!/usr/bin/env python3
"""Add the reviewed Rap Brain stop and restart actions to the existing Mac bridge."""

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
STOP = "mac_signed_server_restart.py"
LIFECYCLE = "mac_manager_lifecycle_request.py"
INSTALLER = "mac_install_agent.py"
INSTALLER_SHA = "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"
LABEL = "com.gns.rapbrain.remote.p0"
BASELINE = {
    BRIDGE: "d148dccbede14e7b4a77ebefc1cfa460878a622d53965dab9830af0bcd698c92",
    ADAPTER: "900650abead9d019c2358d41076b5196f0dbe5f687583180c906b59b7da2ef97",
    STARTUP: "deabf5ecf084c186e8fa5184b2111b379866553ae76a3cc9d4d352c7802540f5",
    STOP: "12bbfd8ed4e67107a4f5caf8ee88a1c1d82647a73679f7bc11a9df66e6eae97c",
}
WITH_DASHBOARD_PROOF = BASELINE | {
    ADAPTER: "4db7de0efb15f7cae34d6312ac00688e0caa7358661529115ccb50c50279c2bf",
    STARTUP: "89ed14eb8f72ec6e32f94b082dfd9f7a8a80ecd100dafcef7e653a3d05bef6a4",
}
INCOMING = {
    BRIDGE: "2f72f81a43b8a2ed80b6dc3d5f1c729cfbad043fae1c5a95f4250c68e0e4b629",
    ADAPTER: "9657669b3c569e6727021206710b0889bc5f4769abace5ce56b876e37a1e1767",
    STARTUP: "880abb06c441cd975e3b9f8b7f7daad4f289663d861e1385ac42eab4e6e7f121",
    STOP: "6ea81d309f20a479164dcae48819868158970bb029f7ca3c44c8082dbf936032",
    LIFECYCLE: "76f00318f8c2636d4dc435f09b6226790ef1e9fdc06534d5f4207397b97fccde",
}


def matches(path, expected):
    return (path.resolve() == path and path.is_file()
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected)


def main():
    if sys.platform != "darwin" or len(sys.argv) != 1:
        raise ValueError("Activation réservée au Mac de Rap Brain.")
    home = Path.home().resolve()
    source = Path(__file__).resolve().parent
    target = home / "Library/Application Support/RapBrainRemoteBridge"
    if not all(matches(source / name, digest) for name, digest in INCOMING.items()):
        raise ValueError("Les fichiers du nouveau pont sont inattendus.")
    if not matches(source / INSTALLER, INSTALLER_SHA):
        raise ValueError("L’installateur du pont est inattendu.")
    sys.path[0:0] = [str(source), str(target)]
    import mac_bridge
    from mac_install_agent import upgrade_manager_bridge

    if not callable(mac_bridge.advance_lifecycle_task):
        raise ValueError("Le module de redémarrage distant est indisponible.")
    if not all(matches(target / name, digest) for name, digest in INCOMING.items()):
        baseline = next((version for version in (BASELINE, WITH_DASHBOARD_PROOF)
                         if all(matches(target / name, digest) for name, digest in version.items())), None)
        if baseline is None:
            raise ValueError("La version installée du pont est inattendue.")
        replacements = {name: digest for name, digest in INCOMING.items() if name != LIFECYCLE}
        upgrade_manager_bridge(home, source, subprocess.run, baseline, replacements,
                               additions={LIFECYCLE: INCOMING[LIFECYCLE]})
    if not all(matches(target / name, digest) for name, digest in INCOMING.items()):
        raise ValueError("La version installée du pont n’a pas été confirmée.")

    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        result = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=5)
        if result.returncode == 0 and re.search(r"^\s*state = running\s*$", result.stdout, re.MULTILINE):
            print("Arrêt et redémarrage distants de Rap Brain activés.")
            return
        time.sleep(0.5)
    raise ValueError("La relance du pont n’a pas été confirmée.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
