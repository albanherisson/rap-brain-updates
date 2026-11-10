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
from mac_preflight import ollama_executable


LABEL = "com.gns.rapbrain.remote.p0"
FILES = ("mac_bridge.py", "mac_preflight.py")
LEGACY_SHA = {"mac_bridge.py": "803dbc3cd5296d64192b6e6c2cd83307eaf82288da2cea943461ce5089c2014a",
              "mac_preflight.py": "974ffefde845f8f763e57bd98db0e07142f1b9f699667e4a8e373b5c139cccf4"}


def paths(home):
    home = Path(home)
    return (home / "Library" / "Application Support" / "RapBrainRemoteBridge",
            home / "Library" / "LaunchAgents" / (LABEL + ".plist"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plist(data, python, ollama=None):
    search = [str(ollama.parent)] if ollama else []
    search += ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), str(data / "mac_bridge.py"), "--watch-keychain"],
        "WorkingDirectory": str(data),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "EnvironmentVariables": {"PATH": ":".join(dict.fromkeys(search))},
        "StandardOutPath": str(data / "agent.out.log"),
        "StandardErrorPath": str(data / "agent.err.log"),
    }


def legacy_plist(data, python):
    definition = plist(data, python)
    del definition["EnvironmentVariables"]
    return definition


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


def replace_owned(path, content, mode):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Fichier du pont manquant ou remplacé par un lien")
    fd, temp = tempfile.mkstemp(prefix=".rapbrain-upgrade-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
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
    definition = plist(data, python, ollama_executable(home))
    put_new_or_same(agent, plistlib.dumps(definition), 0o644)
    domain = "gui/" + str(os.getuid())
    result = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                  capture_output=True, text=True, timeout=20, check=False)
    if result.returncode:
        raise RuntimeError("Activation launchd refusée (code " + str(result.returncode) + ")")
    return LABEL


def upgrade(home=None, source=None, call=subprocess.run):
    if platform.system() != "Darwin":
        raise RuntimeError("Mise à niveau réservée à macOS")
    home = Path.home() if home is None else Path(home)
    source = Path(__file__).resolve().parent if source is None else Path(source)
    data, agent = paths(home)
    if data.is_symlink() or agent.is_symlink() or not agent.is_file():
        raise RuntimeError("Agent installé absent ou remplacé")
    old = {}
    for name in FILES:
        path = data / name
        if path.is_symlink() or not path.is_file() or sha(path) != LEGACY_SHA[name]:
            raise RuntimeError("Version installée du pont inattendue : arrêt")
        incoming = source / name
        if incoming.is_symlink() or not incoming.is_file():
            raise RuntimeError("Source du pont invalide")
        old[path] = path.read_bytes()
    old[agent] = agent.read_bytes()
    try:
        definition = plistlib.loads(old[agent])
    except ValueError:
        raise RuntimeError("Plist installé illisible") from None
    arguments = definition.get("ProgramArguments") if isinstance(definition, dict) else None
    if (not isinstance(arguments, list) or len(arguments) != 3 or
            not isinstance(arguments[0], str) or
            os.path.realpath(arguments[0]) != os.path.realpath(sys.executable) or
            definition != legacy_plist(data, arguments[0])):
        raise RuntimeError("Identité de l'agent installé inattendue")
    token = keychain_token()
    token = ""
    new = {data / name: (source / name).read_bytes() for name in FILES}
    new[agent] = plistlib.dumps(plist(data, definition["ProgramArguments"][0], ollama_executable(home)))
    domain = "gui/" + str(os.getuid())
    stopped = call(["/bin/launchctl", "bootout", domain + "/" + LABEL],
                   capture_output=True, text=True, timeout=20, check=False)
    if stopped.returncode:
        raise RuntimeError("Agent actuel non arrêté : aucun fichier modifié")
    try:
        for path, content in new.items():
            replace_owned(path, content, 0o644 if path == agent else 0o600)
        started = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                       capture_output=True, text=True, timeout=20, check=False)
        if started.returncode:
            raise RuntimeError("Nouvel agent non démarré")
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        for path, content in old.items():
            replace_owned(path, content, 0o644 if path == agent else 0o600)
        restored = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                        capture_output=True, text=True, timeout=20, check=False)
        if restored.returncode:
            raise RuntimeError("Retour arrière écrit, relance manuelle nécessaire") from None
        raise RuntimeError("Mise à niveau refusée ; ancien agent restauré") from None
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
    actions.add_argument("--upgrade", action="store_true")
    actions.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    try:
        if args.install:
            print("Veille activée : " + install())
        elif args.upgrade:
            print("Veille mise à niveau : " + upgrade())
        else:
            stop()
            print("Veille arrêtée. Fichiers et jeton conservés.")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print("Installation refusée : " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
