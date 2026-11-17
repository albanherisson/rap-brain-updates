#!/usr/bin/env python3
"""Add the reviewed Rap Brain stop and restart actions to the existing Mac bridge."""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tempfile


BRIDGE = "mac_bridge.py"
ADAPTER = "mac_manager_install_request.py"
STARTUP = "mac_manager_start_request.py"
STOP = "mac_signed_server_restart.py"
LIFECYCLE = "mac_manager_lifecycle_request.py"
NATIVE = "mac_manager_native.py"
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
WITH_LIFECYCLE = {
    "mac_bridge.py": "2f72f81a43b8a2ed80b6dc3d5f1c729cfbad043fae1c5a95f4250c68e0e4b629",
    "mac_manager_start_request.py": "880abb06c441cd975e3b9f8b7f7daad4f289663d861e1385ac42eab4e6e7f121",
    "mac_manager_install_request.py": "9657669b3c569e6727021206710b0889bc5f4769abace5ce56b876e37a1e1767",
    "mac_signed_server_restart.py": "6ea81d309f20a479164dcae48819868158970bb029f7ca3c44c8082dbf936032",
    "mac_manager_lifecycle_request.py": "76f00318f8c2636d4dc435f09b6226790ef1e9fdc06534d5f4207397b97fccde",
}
WITH_EXIT_CHECK = {
    "mac_bridge.py": "2f72f81a43b8a2ed80b6dc3d5f1c729cfbad043fae1c5a95f4250c68e0e4b629",
    "mac_manager_install_request.py": "10541d31caf62a4c2035b2292caa830c38e0b73c3b0c10c955ed1abf620f2aa9",
    "mac_manager_start_request.py": "880abb06c441cd975e3b9f8b7f7daad4f289663d861e1385ac42eab4e6e7f121",
    "mac_signed_server_restart.py": "7d3b2d04b2d3c09ab100f9e9c781b4720daabcbcec55009f083386abadcad7dc",
    "mac_manager_lifecycle_request.py": "76f00318f8c2636d4dc435f09b6226790ef1e9fdc06534d5f4207397b97fccde",
}
WITH_NATIVE_WINDOW = {
    BRIDGE: "2f72f81a43b8a2ed80b6dc3d5f1c729cfbad043fae1c5a95f4250c68e0e4b629",
    ADAPTER: "10541d31caf62a4c2035b2292caa830c38e0b73c3b0c10c955ed1abf620f2aa9",
    STARTUP: "880abb06c441cd975e3b9f8b7f7daad4f289663d861e1385ac42eab4e6e7f121",
    STOP: "7d3b2d04b2d3c09ab100f9e9c781b4720daabcbcec55009f083386abadcad7dc",
    LIFECYCLE: "d467878fb715b5bef6f30fa68627899554f050d31359f07ed72dd5e0d2726ef3",
    NATIVE: "13d4c58d846d30da372b46beea1c8653b0ba3d0a22a2e3891829a5f5604039a0",
}
WITH_NATIVE_LAUNCH = WITH_NATIVE_WINDOW | {'mac_manager_lifecycle_request.py': '5fc6bb14483029176e2379788dd9d66110bbd40178f2d5578bedc08bc35e6065', 'mac_manager_native.py': 'e8b77d3d7b537ee103a6479810899fae65b68a565a62d48bbf33fffdd799b3c1'}
INCOMING = WITH_NATIVE_LAUNCH | {NATIVE: 'f08eb84f93344df2f975f52f0ca9af682202d6647237d104ee181e235a4dd852'}


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
    from mac_manager_native import SWIFT

    if not callable(mac_bridge.advance_lifecycle_task):
        raise ValueError("Le module de redémarrage distant est indisponible.")
    with tempfile.TemporaryDirectory(prefix="rapbrain-native-check-") as folder:
        swift = Path(folder) / "manager_window.swift"
        swift.write_text(SWIFT, encoding="utf-8")
        compiled = subprocess.run(["/usr/bin/swiftc", "-typecheck", str(swift)],
                                  capture_output=True, stdin=subprocess.DEVNULL, timeout=90)
        if compiled.returncode:
            raise ValueError("Le contrôle natif du Manager n’a pas pu être compilé.")
    if not all(matches(target / name, digest) for name, digest in INCOMING.items()):
        baseline = next((version for version in (BASELINE, WITH_DASHBOARD_PROOF, WITH_LIFECYCLE, WITH_EXIT_CHECK, WITH_NATIVE_WINDOW, WITH_NATIVE_LAUNCH)
                         if all(matches(target / name, digest) for name, digest in version.items())), None)
        if baseline is None:
            raise ValueError("La version installée du pont est inattendue.")
        additions = {name: digest for name, digest in INCOMING.items() if name not in baseline}
        replacements = {name: digest for name, digest in INCOMING.items() if name not in additions}
        upgrade_manager_bridge(home, source, subprocess.run, baseline, replacements,
                               additions=additions)
    if not all(matches(target / name, digest) for name, digest in INCOMING.items()):
        raise ValueError("La version installée du pont n’a pas été confirmée.")

    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        result = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=5)
        if result.returncode == 0 and re.search(r"^\s*state = running\s*$", result.stdout, re.MULTILINE):
            print("Identification signée du Manager et redémarrage distants activés.")
            return
        time.sleep(0.5)
    raise ValueError("La relance du pont n’a pas été confirmée.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
