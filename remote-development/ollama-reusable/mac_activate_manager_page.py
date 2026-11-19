#!/usr/bin/env python3
"""Activate only the reviewed fixed-page action in the installed Mac bridge."""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time


LABEL = "com.gns.rapbrain.remote.p0"
INSTALLER_SHA = "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"
BASELINE = {
    "mac_bridge.py": "2f72f81a43b8a2ed80b6dc3d5f1c729cfbad043fae1c5a95f4250c68e0e4b629",
    "mac_manager_start_request.py": "880abb06c441cd975e3b9f8b7f7daad4f289663d861e1385ac42eab4e6e7f121",
    "mac_manager_lifecycle_request.py": "5fc6bb14483029176e2379788dd9d66110bbd40178f2d5578bedc08bc35e6065",
    "mac_manager_native.py": "f08eb84f93344df2f975f52f0ca9af682202d6647237d104ee181e235a4dd852",
}
INCOMING = {
    "mac_bridge.py": "c1d827115951d700ef99766f3ade0a90dbd0d493162170e26bc352f49b73acfa",
}
ADDITIONS = {
    "mac_manager_page_request.py": "785e20b950b172f324f3dd44a910c70ba1375923cf4dd3e5edcc6a5957a0accc",
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
    if not all(matches(source / name, digest) for name, digest in (INCOMING | ADDITIONS).items()):
        raise ValueError("Les fichiers de la nouvelle action sont inattendus.")
    if not matches(source / "mac_install_agent.py", INSTALLER_SHA):
        raise ValueError("L’installateur du pont est inattendu.")
    sys.path[0:0] = [str(source), str(target)]
    from mac_install_agent import upgrade_manager_bridge
    from mac_manager_page_request import parse_page_task

    if not callable(parse_page_task):
        raise ValueError("L’action de page est indisponible.")
    if not all(matches(target / name, digest) for name, digest in (BASELINE | INCOMING | ADDITIONS).items()):
        if not all(matches(target / name, digest) for name, digest in BASELINE.items()):
            raise ValueError("La version installée du pont est inattendue.")
        upgrade_manager_bridge(home, source, subprocess.run, BASELINE, INCOMING, additions=ADDITIONS)
    if not all(matches(target / name, digest) for name, digest in (BASELINE | INCOMING | ADDITIONS).items()):
        raise ValueError("L’installation de la nouvelle action n’a pas été confirmée.")
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        result = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=5)
        if result.returncode == 0 and re.search(r"^\s*state = running\s*$", result.stdout, re.MULTILINE):
            print("Ouverture distante de la page Rap Brain activée.")
            return
        time.sleep(0.5)
    raise ValueError("La relance du pont n’a pas été confirmée.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
