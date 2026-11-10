#!/usr/bin/env python3
"""Install the bounded Rap Brain pilot as a per-user macOS LaunchAgent."""

import argparse
import hashlib
import os
import platform
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

from mac_bridge import keychain_token


LABEL = "com.gns.rapbrain.remote.p0"
FILES = ("mac_bridge.py", "mac_preflight.py")


def paths(home):
    home = Path(home)
    return (home / "Library" / "Application Support" / "RapBrainRemoteBridge",
            home / "Library" / "LaunchAgents" / (LABEL + ".plist"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plist(data, python):
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), str(data / "mac_bridge.py"), "--watch-keychain"],
        "WorkingDirectory": str(data),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "StandardOutPath": str(data / "agent.out.log"),
        "StandardErrorPath": str(data / "agent.err.log"),
    }


def put_new_or_same(dest, content, mode):
    if dest.is_symlink():
        raise RuntimeError("Lien symbolique à la place d'un fichier du pont")
    if dest.exists():
        if dest.read_bytes() != content:
            raise RuntimeError("Fichier du pont déjà présent avec un autre contenu : arrêt")
        return
    fd, temp = tempfile.mkstemp(prefix=".rapbrain-", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        # Hard-link creation fails if the destination appeared meanwhile.
        # This preserves a pre-existing file even under a concurrent install.
        try:
            os.link(temp, dest)
        except FileExistsError:
            raise RuntimeError("Fichier apparu pendant l'installation") from None
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def install(home=None, source=None, python=None, call=subprocess.run):
    if platform.system() != "Darwin":
        raise RuntimeError("Installation réservée à macOS")
    home = Path.home() if home is None else Path(home)
    source = Path(__file__).resolve().parent if source is None else Path(source)
    python = sys.executable if python is None else python
    data, agent = paths(home)
    if data.is_symlink() or agent.parent.is_symlink():
        raise RuntimeError("Dossier de destination remplacé par un lien")
    for name in FILES:
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("Source du pont absente ou remplacée par un lien")
    # Fail before creating files when the token is unavailable. Never print it.
    token = keychain_token()
    token = ""
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    agent.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in FILES:
        content = (source / name).read_bytes()
        put_new_or_same(data / name, content, 0o600)
        if sha(data / name) != hashlib.sha256(content).hexdigest():
            raise RuntimeError("Copie du pont non conforme")
    definition = plist(data, python)
    put_new_or_same(agent, plistlib.dumps(definition), 0o644)
    domain = "gui/" + str(os.getuid())
    result = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                  capture_output=True, text=True, timeout=20, check=False)
    if result.returncode:
        raise RuntimeError("Activation launchd refusée (code " + str(result.returncode) + ")")
    return LABEL


def stop(call=subprocess.run):
    domain = "gui/" + str(os.getuid())
    result = call(["/bin/launchctl", "bootout", domain + "/" + LABEL],
                  capture_output=True, text=True, timeout=20, check=False)
    if result.returncode:
        raise RuntimeError("Arrêt launchd refusé (code " + str(result.returncode) + ")")


def main():
    parser = argparse.ArgumentParser(description="Installation de la veille Rap Brain P0")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--install", action="store_true")
    actions.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    try:
        if args.install:
            print("Veille activée : " + install())
        else:
            stop()
            print("Veille arrêtée. Fichiers et jeton conservés.")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print("Installation refusée : " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
