#!/usr/bin/env python3
"""Install the bounded Rap Brain pilot as a per-user macOS LaunchAgent."""

import argparse
import errno
import hashlib
import os
import platform
import plistlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mac_bridge import keychain_token
from mac_private_source_trial import keychain_token as private_keychain_token
from mac_preflight import ollama_executable


LABEL = "com.gns.rapbrain.remote.p0"
FILES = ("mac_bridge.py", "mac_preflight.py")
PRIVATE_FILE = "mac_private_source_trial.py"
CURRENT_SHA = {"mac_bridge.py": "803dbc3cd5296d64192b6e6c2cd83307eaf82288da2cea943461ce5089c2014a",
               "mac_preflight.py": "ab32901dc7484ecafeab1d54985119763eb07e00d1e2e9a5e1c4ef51b719546b"}
PRIVATE_TRIAL_SHA = {"mac_bridge.py": "e0d4dcbd7b24a3ccf57179bd03d47dd50ccf14255dc34c02ad456e9ce70b4c88",
                     "mac_preflight.py": "ab32901dc7484ecafeab1d54985119763eb07e00d1e2e9a5e1c4ef51b719546b",
                     PRIVATE_FILE: "7f6c347bb7055140aceaedb7eee83452b564b8af00a3c9837f35f7939a8ac03b"}
SOURCE_VALIDATION_SHA = {"mac_bridge.py": "c766e84bedf2d0ae23444080ad8eae843adf41be46e1db8a15ccfbbbf02ae2fe",
                         "mac_preflight.py": "ab32901dc7484ecafeab1d54985119763eb07e00d1e2e9a5e1c4ef51b719546b",
                         PRIVATE_FILE: "1484d5fec6ff591bc5ce02dc66d5c6af67735e1151c1aedf9a4fe1d12795184a"}
REVIEWED_FILE = "mac_reviewed_test_trial.py"
REVIEWED_INSTALLED_SHA = {"mac_bridge.py": "4a664f2bf54099f486b19503e422214bd6b304c247b402770e5a5a4fd652784c",
                          "mac_preflight.py": "ab32901dc7484ecafeab1d54985119763eb07e00d1e2e9a5e1c4ef51b719546b",
                          PRIVATE_FILE: "907551daea2195a3e470516999706d3ac4ea68216f787b6b214ef9d39dc72bb0",
                          REVIEWED_FILE: "644e1c99cea699164cccb6a272bb70c502ec15ff78c515869e4026d8771db414"}
MANAGER_LAB_FILE = "mac_manager_lab_trial.py"
MANAGER_INVENTORY_FILE = "mac_manager_inventory.py"
MANAGER_LAB_INSTALLED_SHA = {**REVIEWED_INSTALLED_SHA,
                             "mac_bridge.py": "620c42b7c7a67406533f812b81b956ab2f9ce38982e2cb21c6071b6cfe144c4c",
                             MANAGER_LAB_FILE: "6f82e1074636c39421791f1ca61bfd844a82af1db7e44753b402f227a6e42c79"}
MANAGER_INVENTORY_INSTALLED_SHA = {**MANAGER_LAB_INSTALLED_SHA,
                                   "mac_bridge.py": "a203bffba2adc093bce991016dc4ea73faa68255b60b924b055c31b099aea3f1",
                                   MANAGER_INVENTORY_FILE: "03493fec5385584a6f3e52c5075abe2d494df0e850c8f1d9db76d9c259cc699c"}
MANAGER_PROCESS_INSTALLED_SHA = {**MANAGER_INVENTORY_INSTALLED_SHA,
                                 "mac_bridge.py": "af2b737a6f5b2050be6604b19663b56169b81b4eaf8bf11e5345969bb1f7a6df",
                                 MANAGER_INVENTORY_FILE: "a28ab8cd06b7222377e0a08bc22b85d63ea49f71b4a397330db65d5bf3d5b47e"}
REMOTE_MANAGER_BRIDGE_SHA = "6fadaf071ff4a926b0d4cd5eadae95aaf88dc0e74ab28acca43f0ac99f18b760"
REMOTE_TRIAL_INSTALLED_SHA = {**MANAGER_PROCESS_INSTALLED_SHA, "mac_bridge.py": REMOTE_MANAGER_BRIDGE_SHA}
REMOTE_INSTALL_BRIDGE_SHA = "0567ee64b6c809c09821b858ab79a637749b2f316f05548f66543acac3eae01e"
REMOTE_INSTALL_FILES = {
    "mac_manager_install_request.py": "59932d451cd67e8537a66130882e8b2a007ed1eba59b53c7e711b81b413d4828",
    "manager_remote_request.py": "bef588df37337ad220d4916057f9c02cd2a5e971ab8f7018a8bda95010031d31",
}
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
    for name in FILES + (PRIVATE_FILE,):
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("Source du pont absente ou remplacée par un lien")
    # Fail before creating files when the token is unavailable. Never print it.
    token = keychain_token()
    token = ""
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    agent.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in FILES + (PRIVATE_FILE,):
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


def upgrade_private_trial(home=None, source=None, call=subprocess.run):
    """Replace only the known health-only agent, preserving its existing plist."""
    if platform.system() != "Darwin":
        raise RuntimeError("Mise à niveau réservée à macOS")
    home = Path.home() if home is None else Path(home)
    source = Path(__file__).resolve().parent if source is None else Path(source)
    data, agent = paths(home)
    bridge, private = data / "mac_bridge.py", data / PRIVATE_FILE
    incoming = source / "mac_bridge.py"
    incoming_private = source / PRIVATE_FILE
    if data.is_symlink() or agent.is_symlink() or not agent.is_file():
        raise RuntimeError("Agent installé absent ou remplacé")
    if private.exists() or private.is_symlink():
        raise RuntimeError("Fichier privé déjà installé : aucun remplacement")
    for name, expected in CURRENT_SHA.items():
        path = data / name
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError("Version installée du pont inattendue : arrêt")
    for path in (incoming, incoming_private):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Nouvelle source du pont absente ou remplacée")
    old_bridge = bridge.read_bytes()
    old_plist = agent.read_bytes()
    try:
        definition = plistlib.loads(old_plist)
    except ValueError:
        raise RuntimeError("Plist installé illisible") from None
    arguments = definition.get("ProgramArguments") if isinstance(definition, dict) else None
    if (not isinstance(arguments, list) or len(arguments) != 3 or
            not isinstance(arguments[0], str) or
            definition != plist(data, arguments[0], ollama_executable(home))):
        raise RuntimeError("Identité de l'agent installé inattendue")
    token = keychain_token()
    token = ""
    private_token = private_keychain_token()
    private_token = ""
    domain = "gui/" + str(os.getuid())
    stopped = call(["/bin/launchctl", "bootout", domain + "/" + LABEL],
                   capture_output=True, text=True, timeout=20, check=False)
    if stopped.returncode:
        raise RuntimeError("Agent actuel non arrêté : aucun fichier modifié")
    try:
        put_new_or_same(private, incoming_private.read_bytes(), 0o600)
        replace_owned(bridge, incoming.read_bytes(), 0o600)
        started = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                       capture_output=True, text=True, timeout=20, check=False)
        if started.returncode:
            raise RuntimeError("Nouvel agent non démarré")
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        replace_owned(bridge, old_bridge, 0o600)
        if private.exists() and not private.is_symlink():
            private.unlink()
        restored = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                        capture_output=True, text=True, timeout=20, check=False)
        if restored.returncode:
            raise RuntimeError("Retour arrière écrit, relance manuelle nécessaire") from None
        raise RuntimeError("Mise à niveau refusée ; ancien agent restauré") from None
    return LABEL


def upgrade_source_validation(home=None, source=None, call=subprocess.run):
    """Upgrade the proven private-read agent without changing launchd identity."""
    if platform.system() != "Darwin":
        raise RuntimeError("Mise à niveau réservée à macOS")
    home = Path.home() if home is None else Path(home)
    source = Path(__file__).resolve().parent if source is None else Path(source)
    data, agent = paths(home)
    if data.is_symlink() or agent.is_symlink() or not agent.is_file():
        raise RuntimeError("Agent installé absent ou remplacé")
    old = {}
    for name, expected in PRIVATE_TRIAL_SHA.items():
        path = data / name
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError("Version installée du pont inattendue : arrêt")
        if name in ("mac_bridge.py", PRIVATE_FILE):
            incoming = source / name
            if incoming.is_symlink() or not incoming.is_file():
                raise RuntimeError("Nouvelle source du pont absente ou remplacée")
            old[path] = path.read_bytes()
    before = agent.read_bytes()
    try:
        definition = plistlib.loads(before)
    except ValueError:
        raise RuntimeError("Plist installé illisible") from None
    arguments = definition.get("ProgramArguments") if isinstance(definition, dict) else None
    if (not isinstance(arguments, list) or len(arguments) != 3 or
            not isinstance(arguments[0], str) or
            definition != plist(data, arguments[0], ollama_executable(home))):
        raise RuntimeError("Identité de l'agent installé inattendue")
    token = keychain_token()
    token = ""
    private_token = private_keychain_token()
    private_token = ""
    domain = "gui/" + str(os.getuid())
    stopped = call(["/bin/launchctl", "bootout", domain + "/" + LABEL],
                   capture_output=True, text=True, timeout=20, check=False)
    if stopped.returncode:
        raise RuntimeError("Agent actuel non arrêté : aucun fichier modifié")
    try:
        for path in old:
            replace_owned(path, (source / path.name).read_bytes(), 0o600)
        started = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                       capture_output=True, text=True, timeout=20, check=False)
        if started.returncode:
            raise RuntimeError("Nouvel agent non démarré")
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        for path, content in old.items():
            replace_owned(path, content, 0o600)
        restored = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                        capture_output=True, text=True, timeout=20, check=False)
        if restored.returncode:
            raise RuntimeError("Retour arrière écrit, relance manuelle nécessaire") from None
        raise RuntimeError("Mise à niveau refusée ; ancien agent restauré") from None
    return LABEL


def upgrade_reviewed_test(home=None, source=None, call=subprocess.run):
    """Upgrade the pinned source-validation agent, restoring it if launchd fails."""
    if platform.system() != "Darwin":
        raise RuntimeError("Mise à niveau réservée à macOS")
    home = Path.home() if home is None else Path(home)
    source = Path(__file__).resolve().parent if source is None else Path(source)
    data, agent = paths(home)
    if data.is_symlink() or agent.is_symlink() or not agent.is_file():
        raise RuntimeError("Agent installé absent ou remplacé")
    old = {}
    for name, expected in SOURCE_VALIDATION_SHA.items():
        path = data / name
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError("Version installée du pont inattendue : arrêt")
        if name != "mac_preflight.py":
            old[path] = path.read_bytes()
    reviewed = data / REVIEWED_FILE
    if reviewed.exists() or reviewed.is_symlink():
        raise RuntimeError("Tests revus déjà installés : aucun remplacement")
    for name in ("mac_bridge.py", PRIVATE_FILE, REVIEWED_FILE):
        incoming = source / name
        if incoming.is_symlink() or not incoming.is_file():
            raise RuntimeError("Nouvelle source du pont absente ou remplacée")
    try:
        definition = plistlib.loads(agent.read_bytes())
    except ValueError:
        raise RuntimeError("Plist installé illisible") from None
    arguments = definition.get("ProgramArguments") if isinstance(definition, dict) else None
    if (not isinstance(arguments, list) or len(arguments) != 3 or
            not isinstance(arguments[0], str) or
            definition != plist(data, arguments[0], ollama_executable(home))):
        raise RuntimeError("Identité de l'agent installé inattendue")
    keychain_token()
    private_keychain_token()
    domain = "gui/" + str(os.getuid())
    stopped = call(["/bin/launchctl", "bootout", domain + "/" + LABEL],
                   capture_output=True, text=True, timeout=20, check=False)
    if stopped.returncode:
        raise RuntimeError("Agent actuel non arrêté : aucun fichier modifié")
    try:
        put_new_or_same(reviewed, (source / REVIEWED_FILE).read_bytes(), 0o600)
        for path in old:
            replace_owned(path, (source / path.name).read_bytes(), 0o600)
        started = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                       capture_output=True, text=True, timeout=20, check=False)
        if started.returncode:
            raise RuntimeError("Nouvel agent non démarré")
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        for path, content in old.items():
            replace_owned(path, content, 0o600)
        if reviewed.is_file() and not reviewed.is_symlink():
            reviewed.unlink()
        restored = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                        capture_output=True, text=True, timeout=20, check=False)
        if restored.returncode:
            raise RuntimeError("Retour arrière écrit, relance manuelle nécessaire") from None
        raise RuntimeError("Mise à niveau refusée ; ancien agent restauré") from None
    return LABEL


def upgrade_manager_lab(home=None, source=None, call=subprocess.run):
    """Add only the pinned Manager laboratory to the known reviewed-test agent."""
    if platform.system() != "Darwin":
        raise RuntimeError("Mise à niveau réservée à macOS")
    home = Path.home() if home is None else Path(home)
    source = Path(__file__).resolve().parent if source is None else Path(source)
    data, agent = paths(home)
    if data.is_symlink() or agent.is_symlink() or not agent.is_file():
        raise RuntimeError("Agent installé absent ou remplacé")
    for name, expected in REVIEWED_INSTALLED_SHA.items():
        path = data / name
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError("Version installée du pont inattendue : arrêt")
    bridge, manager = data / "mac_bridge.py", data / MANAGER_LAB_FILE
    if manager.exists() or manager.is_symlink():
        raise RuntimeError("Laboratoire Manager déjà installé")
    for name in ("mac_bridge.py", MANAGER_LAB_FILE):
        incoming = source / name
        if incoming.is_symlink() or not incoming.is_file():
            raise RuntimeError("Nouvelle source du pont absente ou remplacée")
    try:
        definition = plistlib.loads(agent.read_bytes())
    except ValueError:
        raise RuntimeError("Plist installé illisible") from None
    arguments = definition.get("ProgramArguments") if isinstance(definition, dict) else None
    if (not isinstance(arguments, list) or len(arguments) != 3 or
            not isinstance(arguments[0], str) or
            definition != plist(data, arguments[0], ollama_executable(home))):
        raise RuntimeError("Identité de l'agent installé inattendue")
    keychain_token()
    private_keychain_token()
    old_bridge = bridge.read_bytes()
    domain = "gui/" + str(os.getuid())
    stopped = call(["/bin/launchctl", "bootout", domain + "/" + LABEL],
                   capture_output=True, text=True, timeout=20, check=False)
    if stopped.returncode:
        raise RuntimeError("Agent actuel non arrêté : aucun fichier modifié")
    stage = "copie du laboratoire"
    try:
        put_new_or_same(manager, (source / MANAGER_LAB_FILE).read_bytes(), 0o600)
        stage = "remplacement du pont"
        replace_owned(bridge, (source / "mac_bridge.py").read_bytes(), 0o600)
        stage = "redémarrage launchd"
        started = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                       capture_output=True, text=True, timeout=20, check=False)
        if started.returncode:
            raise RuntimeError("code " + str(started.returncode))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        # Only report the controlled step and error class/code: no paths,
        # launchctl output or credentials from the host are echoed.
        detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        replace_owned(bridge, old_bridge, 0o600)
        if manager.is_file() and not manager.is_symlink():
            manager.unlink()
        restored = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                        capture_output=True, text=True, timeout=20, check=False)
        if restored.returncode:
            raise RuntimeError("Retour arrière écrit, relance manuelle nécessaire ; échec à l'étape " +
                               stage + " (" + detail + ")") from None
        raise RuntimeError("Mise à niveau refusée à l'étape " + stage + " (" + detail +
                           ") ; ancien agent restauré") from None
    return LABEL


def upgrade_manager_inventory(home=None, source=None, call=subprocess.run):
    """Add a fixed-path, read-only inventory to the proven Manager laboratory."""
    if platform.system() != "Darwin":
        raise RuntimeError("Mise à niveau réservée à macOS")
    home = Path.home() if home is None else Path(home)
    source = Path(__file__).resolve().parent if source is None else Path(source)
    data, agent = paths(home)
    if data.is_symlink() or agent.is_symlink() or not agent.is_file():
        raise RuntimeError("Agent installé absent ou remplacé")
    for name, expected in MANAGER_LAB_INSTALLED_SHA.items():
        path = data / name
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError("Version installée du pont inattendue : arrêt")
    bridge, inventory = data / "mac_bridge.py", data / MANAGER_INVENTORY_FILE
    if inventory.exists() or inventory.is_symlink():
        raise RuntimeError("Inventaire Manager déjà installé")
    for name in ("mac_bridge.py", MANAGER_INVENTORY_FILE):
        incoming = source / name
        if incoming.is_symlink() or not incoming.is_file():
            raise RuntimeError("Nouvelle source du pont absente ou remplacée")
    try:
        definition = plistlib.loads(agent.read_bytes())
    except ValueError:
        raise RuntimeError("Plist installé illisible") from None
    arguments = definition.get("ProgramArguments") if isinstance(definition, dict) else None
    if (not isinstance(arguments, list) or len(arguments) != 3 or
            not isinstance(arguments[0], str) or
            definition != plist(data, arguments[0], ollama_executable(home))):
        raise RuntimeError("Identité de l'agent installé inattendue")
    keychain_token()
    private_keychain_token()
    old_bridge = bridge.read_bytes()
    domain = "gui/" + str(os.getuid())
    stopped = call(["/bin/launchctl", "bootout", domain + "/" + LABEL],
                   capture_output=True, text=True, timeout=20, check=False)
    if stopped.returncode:
        raise RuntimeError("Agent actuel non arrêté : aucun fichier modifié")
    stage = "copie de l'inventaire"
    try:
        put_new_or_same(inventory, (source / MANAGER_INVENTORY_FILE).read_bytes(), 0o600)
        stage = "remplacement du pont"
        replace_owned(bridge, (source / "mac_bridge.py").read_bytes(), 0o600)
        stage = "redémarrage launchd"
        started = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                       capture_output=True, text=True, timeout=20, check=False)
        if started.returncode:
            raise RuntimeError("code " + str(started.returncode))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        replace_owned(bridge, old_bridge, 0o600)
        if inventory.is_file() and not inventory.is_symlink():
            inventory.unlink()
        restored = call(["/bin/launchctl", "bootstrap", domain, str(agent)],
                        capture_output=True, text=True, timeout=20, check=False)
        if restored.returncode:
            raise RuntimeError("Retour arrière écrit, relance manuelle nécessaire ; échec à l'étape " +
                               stage + " (" + detail + ")") from None
        raise RuntimeError("Mise à niveau refusée à l'étape " + stage + " (" + detail +
                           ") ; ancien agent restauré") from None
    return LABEL


def bootstrap_after_bootout(domain, agent, call):
    command = ["/bin/launchctl", "bootstrap", domain, str(agent)]
    # launchd may briefly retain the service label after a successful bootout.
    for attempt in range(11):
        if attempt:
            time.sleep(1)
        result = call(command, capture_output=True, text=True, timeout=20, check=False)
        if result.returncode != errno.EIO:
            break
    return result


def upgrade_manager_bridge(home, source, call, installed, incoming, *, additions=None):
    """Replace the named files of a known agent and restore them if restart fails."""
    if platform.system() != "Darwin":
        raise RuntimeError("Mise à niveau réservée à macOS")
    home = Path.home() if home is None else Path(home)
    source = Path(__file__).resolve().parent if source is None else Path(source)
    data, agent = paths(home)
    if data.is_symlink() or agent.is_symlink() or not agent.is_file():
        raise RuntimeError("Agent installé absent ou remplacé")
    def matches(name, expected):
        path = data / name
        return not path.is_symlink() and path.is_file() and sha(path) == expected
    already_updated = bool(additions) and all(matches(name, expected) for name, expected in
                                             (installed | incoming | additions).items())
    if not already_updated and not all(matches(name, expected) for name, expected in installed.items()):
        raise RuntimeError("Version installée du pont inattendue : arrêt")
    old = {}
    new = {}
    added = {}
    for name, expected in (incoming | (additions or {})).items():
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Nouvelle source du pont absente ou remplacée")
        content = path.read_bytes()
        if expected is not None and hashlib.sha256(content).hexdigest() != expected:
            raise RuntimeError("Empreinte de la nouvelle source du pont inattendue")
        if additions and name in additions:
            destination = data / name
            if not already_updated and os.path.lexists(destination):
                raise RuntimeError("Un nouveau fichier du pont existe déjà : arrêt")
            added[destination] = content
        else:
            old[data / name] = (data / name).read_bytes()
            new[data / name] = content
    try:
        definition = plistlib.loads(agent.read_bytes())
    except ValueError:
        raise RuntimeError("Plist installé illisible") from None
    arguments = definition.get("ProgramArguments") if isinstance(definition, dict) else None
    if (not isinstance(arguments, list) or len(arguments) != 3 or
            not isinstance(arguments[0], str) or
            definition != plist(data, arguments[0], ollama_executable(home))):
        raise RuntimeError("Identité de l'agent installé inattendue")
    keychain_token()
    private_keychain_token()
    if already_updated:
        return LABEL
    domain = "gui/" + str(os.getuid())
    stopped = call(["/bin/launchctl", "bootout", domain + "/" + LABEL],
                   capture_output=True, text=True, timeout=20, check=False)
    if stopped.returncode:
        raise RuntimeError("Agent actuel non arrêté : aucun fichier modifié")
    stage = "remplacement du pont"
    created = []
    try:
        for path, content in added.items():
            stage = "ajout de " + path.name
            put_new_or_same(path, content, 0o600)
            created.append(path)
        for path, content in new.items():
            stage = "remplacement de " + path.name
            replace_owned(path, content, 0o600)
        stage = "redémarrage launchd"
        started = bootstrap_after_bootout(domain, agent, call)
        if started.returncode:
            raise RuntimeError("code " + str(started.returncode))
    except (RuntimeError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        for path, content in old.items():
            replace_owned(path, content, 0o600)
        for path in created:
            if not path.is_symlink() and path.is_file() and path.read_bytes() == added[path]:
                path.unlink()
        restored = bootstrap_after_bootout(domain, agent, call)
        if restored.returncode:
            raise RuntimeError("Retour arrière écrit, relance manuelle nécessaire ; échec à l'étape " +
                               stage + " (" + detail + ")") from None
        raise RuntimeError("Mise à niveau refusée à l'étape " + stage + " (" + detail +
                           ") ; ancien agent restauré") from None
    return LABEL


def upgrade_manager_process(home=None, source=None, call=subprocess.run):
    """Add a coarse read-only process census to the known inventory agent."""
    return upgrade_manager_bridge(home, source, call, MANAGER_INVENTORY_INSTALLED_SHA,
                                  {"mac_bridge.py": None, MANAGER_INVENTORY_FILE: None})


def upgrade_manager_remote_update_trial(home=None, source=None, call=subprocess.run):
    """Allow the one reviewed remote update trial on disposable copies."""
    return upgrade_manager_bridge(home, source, call, MANAGER_PROCESS_INSTALLED_SHA,
                                  {"mac_bridge.py": REMOTE_MANAGER_BRIDGE_SHA})


def upgrade_manager_install_requests(home=None, source=None, call=subprocess.run):
    """Install the bridge that hands privately authorized releases to the Manager."""
    return upgrade_manager_bridge(home, source, call, REMOTE_TRIAL_INSTALLED_SHA,
                                  {"mac_bridge.py": REMOTE_INSTALL_BRIDGE_SHA},
                                  additions=REMOTE_INSTALL_FILES)


def main():
    parser = argparse.ArgumentParser(description="Installation de la veille Rap Brain P0")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--install", action="store_true")
    actions.add_argument("--upgrade", action="store_true")
    actions.add_argument("--upgrade-private-trial", action="store_true")
    actions.add_argument("--upgrade-source-validation", action="store_true")
    actions.add_argument("--upgrade-reviewed-test", action="store_true")
    actions.add_argument("--upgrade-manager-lab", action="store_true")
    actions.add_argument("--upgrade-manager-inventory", action="store_true")
    actions.add_argument("--upgrade-manager-process", action="store_true")
    actions.add_argument("--upgrade-manager-remote-update-trial", action="store_true")
    actions.add_argument("--upgrade-manager-install-requests", action="store_true")
    actions.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    try:
        if args.install:
            print("Veille activée : " + install())
        elif args.upgrade:
            if sha(Path(__file__).resolve().parent / "mac_bridge.py") != CURRENT_SHA["mac_bridge.py"]:
                raise RuntimeError("Ancienne mise à niveau incompatible avec ce pont ; utiliser --upgrade-private-trial")
            print("Veille mise à niveau : " + upgrade())
        elif args.upgrade_private_trial:
            print("Veille privée en lecture seule : " + upgrade_private_trial())
        elif args.upgrade_source_validation:
            print("Validation de sources activée : " + upgrade_source_validation())
        elif args.upgrade_reviewed_test:
            print("Tests revus activés : " + upgrade_reviewed_test())
        elif args.upgrade_manager_lab:
            print("Laboratoire Manager activé : " + upgrade_manager_lab())
        elif args.upgrade_manager_inventory:
            print("Inventaire Manager activé : " + upgrade_manager_inventory())
        elif args.upgrade_manager_process:
            print("Processus Manager activés : " + upgrade_manager_process())
        elif args.upgrade_manager_remote_update_trial:
            print("Essai distant du Manager activé : " + upgrade_manager_remote_update_trial())
        elif args.upgrade_manager_install_requests:
            print("Demandes signées du Manager activées : " + upgrade_manager_install_requests())
        else:
            stop()
            print("Veille arrêtée. Fichiers et jeton conservés.")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print("Installation refusée : " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
