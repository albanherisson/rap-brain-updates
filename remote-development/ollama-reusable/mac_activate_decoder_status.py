#!/usr/bin/env python3
"""Activate only the reviewed, aggregate Decoder status action in the Mac bridge."""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time


LABEL = "com.gns.rapbrain.remote.p0"
INSTALLER = "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"
BASE = {
    "mac_manager_start_request.py": "880abb06c441cd975e3b9f8b7f7daad4f289663d861e1385ac42eab4e6e7f121",
    "mac_manager_native.py": "f08eb84f93344df2f975f52f0ca9af682202d6647237d104ee181e235a4dd852",
    "mac_manager_lifecycle_request.py": "ae9c4a6a72ad5af53a46fb49229fa7cbf79c7a0be3ab956d22ac367c87203d66",
}
PAGE_V1 = {
    "mac_bridge.py": "c1d827115951d700ef99766f3ade0a90dbd0d493162170e26bc352f49b73acfa",
    "mac_manager_page_request.py": "785e20b950b172f324f3dd44a910c70ba1375923cf4dd3e5edcc6a5957a0accc",
}
PAGE_V2 = {
    "mac_bridge.py": "48d35d666bd540fb0da179a3d8300ce25b1f232d3cf8a5f28f5b670ba60344a1",
    "mac_manager_page_request.py": "1740fa3c44febb2be2949efe20d1e1a33c1fbd3118ecf49bcc657725703eff23",
}
NEW = {"mac_bridge.py": "263f5a9397dc07d90735aa46c490c70ce39fa955a73cc28f2b30858ca6feb856",
       "mac_decoder_status_request.py": "893834499e87cc1c9f054286646212f108cf076ae429a37a116d7b83fac0e59b",
       "mac_manager_page_request.py": PAGE_V2["mac_manager_page_request.py"]}


def matches(path, expected):
    return (path.resolve() == path and path.is_file()
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected)


def main():
    if sys.platform != "darwin" or len(sys.argv) != 1:
        raise ValueError("Activation réservée au Mac Rap Brain.")
    home = Path.home().resolve()
    source = Path(__file__).resolve().parent
    target = home / "Library/Application Support/RapBrainRemoteBridge"
    if not matches(source / "mac_install_agent.py", INSTALLER):
        raise ValueError("Installateur du pont inattendu.")
    if not all(matches(source / name, digest) for name, digest in NEW.items()):
        raise ValueError("Source du contrôle Decoder inattendue.")
    if not all(matches(target / name, digest) for name, digest in BASE.items()):
        raise ValueError("Pont installé inattendu.")
    if not all(matches(target / name, digest) for name, digest in NEW.items()):
        baseline = next((BASE | page for page in (PAGE_V1, PAGE_V2)
                         if all(matches(target / name, digest) for name, digest in page.items())), None)
        if baseline is None:
            raise ValueError("Version du pont inattendue.")
        sys.path[0:0] = [str(source), str(target)]
        from mac_install_agent import upgrade_manager_bridge
        incoming = {"mac_bridge.py": NEW["mac_bridge.py"]}
        if baseline["mac_manager_page_request.py"] == PAGE_V1["mac_manager_page_request.py"]:
            incoming["mac_manager_page_request.py"] = NEW["mac_manager_page_request.py"]
        upgrade_manager_bridge(home, source, subprocess.run, baseline, incoming,
                               additions={"mac_decoder_status_request.py": NEW["mac_decoder_status_request.py"]})
    if not all(matches(target / name, digest) for name, digest in NEW.items()):
        raise ValueError("Contrôle Decoder non installé.")
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        result = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=5)
        if result.returncode == 0 and re.search(r"^\s*state = running\s*$", result.stdout, re.MULTILINE):
            print("État distant du Decoder activé.")
            return
        time.sleep(0.5)
    raise ValueError("Relance du pont non confirmée.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
