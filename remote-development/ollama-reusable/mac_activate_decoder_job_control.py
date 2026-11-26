#!/usr/bin/env python3
"""Install the reviewed Decoder status/cancel/retry bridge on the known Mac agent."""

import hashlib
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time


LABEL = "com.gns.rapbrain.remote.p0"
INSTALLER = "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"
INSTALLED = {
    "mac_manager_start_request.py": "880abb06c441cd975e3b9f8b7f7daad4f289663d861e1385ac42eab4e6e7f121",
    "mac_manager_native.py": "f08eb84f93344df2f975f52f0ca9af682202d6647237d104ee181e235a4dd852",
    "mac_manager_lifecycle_request.py": "ae9c4a6a72ad5af53a46fb49229fa7cbf79c7a0be3ab956d22ac367c87203d66",
    "mac_manager_page_request.py": "1740fa3c44febb2be2949efe20d1e1a33c1fbd3118ecf49bcc657725703eff23",
    "mac_decoder_status_request.py": "893834499e87cc1c9f054286646212f108cf076ae429a37a116d7b83fac0e59b",
    "mac_decoder_queue_request.py": "a57b0b096f45d7620c8c5ee4ae1e19d114b48c760d38fdfcacf24b11e4deea16",
    "mac_decoder_track_status_request.py": "b2224b1ff9321d16e94070a9b13a9f81cd6c73ee42bb872013ff9272aa309026",
    "mac_bridge.py": "ef84af6ff96c604c5a93206ad4b7fef082816c7d81f269c518c2382db23f3450",
}
INCOMING = {
    "mac_bridge.py": "95bca2af77d0f940e2684d65b8cf6b7b788b0140790217d064a83fbca5ec7961",
    "mac_decoder_track_status_request.py": "0ba5b71e62515b37c0191ac59d354e78ce3ecdd6ee4a0dd051dcc129389c085b",
}
ADDITIONS = {
    "mac_decoder_job_action_request.py": "206d34fce79b6f0b0c7437f540abf7868e7cac181e4b335d7765e7abe477a36c",
}


def matches(path, digest):
    return path.resolve() == path and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest


def main():
    if sys.platform != "darwin" or len(sys.argv) != 1:
        raise ValueError("Activation réservée au Mac Rap Brain.")
    home = Path.home().resolve()
    source = Path(__file__).resolve().parent
    target = home / "Library/Application Support/RapBrainRemoteBridge"
    if not matches(source / "mac_install_agent.py", INSTALLER):
        raise ValueError("Installateur inattendu.")
    if not all(matches(source / name, digest) for name, digest in (INCOMING | ADDITIONS).items()):
        raise ValueError("Source du contrôle Decoder inattendue.")
    updated = INSTALLED | INCOMING | ADDITIONS
    if not all(matches(target / name, digest) for name, digest in updated.items()):
        if not all(matches(target / name, digest) for name, digest in INSTALLED.items()):
            raise ValueError("Pont installé inattendu.")
        agent = home / "Library/LaunchAgents" / (LABEL + ".plist")
        args = plistlib.loads(agent.read_bytes()).get("ProgramArguments")
        if type(args) is not list or len(args) != 3 or args[1:] != [
                str(target / "mac_bridge.py"), "--watch-keychain"]:
            raise ValueError("Agent installé inattendu.")
        check = subprocess.run([args[0], "-B", "-c",
            "import sys;sys.path[:0]=[" + repr(str(source)) + "," + repr(str(target)) + "];import mac_bridge"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=15)
        if check.returncode:
            raise ValueError("Nouveau pont non importable.")
        sys.path[0:0] = [str(source), str(target)]
        from mac_install_agent import upgrade_manager_bridge
        upgrade_manager_bridge(home, source, subprocess.run, INSTALLED, INCOMING, additions=ADDITIONS)
    if not all(matches(target / name, digest) for name, digest in updated.items()):
        raise ValueError("Contrôle du Decoder non installé.")
    agent = home / "Library/LaunchAgents" / (LABEL + ".plist")
    args = plistlib.loads(agent.read_bytes()).get("ProgramArguments")
    if type(args) is not list or len(args) != 3 or args[1:] != [
            str(target / "mac_bridge.py"), "--watch-keychain"]:
        raise ValueError("Agent installé inattendu.")
    check = subprocess.run([args[0], args[1], "--check-keychain"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=20)
    if check.returncode:
        raise ValueError("Pont installé non importable ou trousseau indisponible.")
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        live = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=5)
        if live.returncode == 0 and re.search(r"^\s*state = running\s*$", live.stdout, re.MULTILINE):
            print("Annulation et reprise distantes du Decoder activées.")
            return
        time.sleep(0.5)
    raise ValueError("Relance du pont non confirmée.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
