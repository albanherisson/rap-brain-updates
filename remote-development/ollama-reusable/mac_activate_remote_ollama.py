#!/usr/bin/env python3
"""Activate the reviewed Ollama trial on the existing macOS bridge."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


BASELINE = "362f2c72ecf262a2cf547c430b3fa02731d8b1f9fececa03b836b9b65d2ed422"
INCOMING = "4c510dc3a6494867f06cbe21dd8cd5c2682817b6634179a4f25d1986a512e207"
INSTALLER = "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"
DEPENDENCIES = {
    "mac_manager_install_request.py": "ec411f60d61f017c6708a413911a2143a7ef2a42a51c2ca5cd9358b144fb5431",
    "mac_manager_sign_request.py": "efbd0a99600a03517fed79b6f3a1465dc3faf29b4d6d292bfa5154ed77b71fa1",
    "mac_manager_inventory.py": "a28ab8cd06b7222377e0a08bc22b85d63ea49f71b4a397330db65d5bf3d5b47e",
    "mac_manager_lab_trial.py": "6f82e1074636c39421791f1ca61bfd844a82af1db7e44753b402f227a6e42c79",
    "mac_preflight.py": "ab32901dc7484ecafeab1d54985119763eb07e00d1e2e9a5e1c4ef51b719546b",
    "mac_private_source_trial.py": "907551daea2195a3e470516999706d3ac4ea68216f787b6b214ef9d39dc72bb0",
    "mac_reviewed_test_trial.py": "644e1c99cea699164cccb6a272bb70c502ec15ff78c515869e4026d8771db414",
    "manager_remote_request.py": "bef588df37337ad220d4916057f9c02cd2a5e971ab8f7018a8bda95010031d31",
}
LABEL = "com.gns.rapbrain.remote.p0"


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Fichier du pont absent ou remplacé")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def activate(home, sources, upgrade, call):
    installed = home / "Library/Application Support/RapBrainRemoteBridge/mac_bridge.py"
    if digest(sources / "mac_bridge.py") != INCOMING:
        raise RuntimeError("Empreinte du nouveau pont inattendue")
    current = digest(installed)
    if current not in (BASELINE, INCOMING):
        raise RuntimeError("Version installée du pont inattendue")
    if current == BASELINE:
        upgrade(home, sources, call, {"mac_bridge.py": BASELINE}, {"mac_bridge.py": INCOMING})
    if digest(installed) != INCOMING:
        raise RuntimeError("Activation du test Ollama non confirmée")
    return {"status": "pass", "remote_ollama_authorizations": "activated"}


def wait_for_agent(label):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        state = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=5)
        if state.returncode == 0 and re.search(r"^\s*state = running\s*$", state.stdout, re.MULTILINE):
            return True
        time.sleep(0.5)
    return False


def main():
    if sys.platform != "darwin":
        raise SystemExit("Activation réservée à macOS")
    sources = Path(__file__).resolve().parent
    home = Path.home().resolve()
    bridge = home / "Library/Application Support/RapBrainRemoteBridge"
    if len(sys.argv) != 1:
        raise SystemExit("Invocation de l’activation invalide")
    if digest(sources / "mac_install_agent.py") != INSTALLER:
        raise SystemExit("Empreinte de l’installateur inattendue")
    if digest(sources / "mac_bridge.py") != INCOMING:
        raise SystemExit("Empreinte du nouveau pont inattendue")
    if any(digest(bridge / name) != expected for name, expected in DEPENDENCIES.items()):
        raise SystemExit("Empreinte d’un module installé inattendue")
    sys.path.insert(0, str(bridge))
    sys.path.insert(0, str(sources))
    from mac_install_agent import upgrade_manager_bridge
    result = activate(home, sources, upgrade_manager_bridge, subprocess.run)
    if not wait_for_agent(LABEL):
        raise SystemExit("Le pont mis à niveau n’est pas encore actif")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc)) from None
