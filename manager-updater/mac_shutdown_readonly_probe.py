#!/usr/bin/env python3
"""Compile the guarded graceful-stop candidate on the owner's Mac in memory.

No server import/execution, process stop, database/config/key access, or write
to the active installation. The fixed-commit public preparers are hash-pinned.
"""
import hashlib
from pathlib import Path
import stat
import sys
import types
import urllib.request

COMMIT = '7117c21aced00be554e547d3b3d6a92b94085ce9'
PINS = {
    'server_lifetime_guard.py': 'ec30c3b0d2d957c2629696833da48ab68a90388e1f50f9c88240bf9046d3a9e6',
    'server_worker_resume_candidate.py': 'c498d630018898f9e1fe8984255acb1c7ccaadd223a9cdc118f530c3bb55fdad',
    'server_graceful_shutdown_candidate.py': 'b53a6beb78825b6305066547d66170add9c2b78af422dd0973a22ee9ceb1e7c4',
}
SERVER = Path.home() / 'Downloads' / 'rap-brain' / 'server.py'
EXPECTED_SERVER = '4380ab4fd97d727ced4521eb66b11004e21f9f15c0eafaee955f1f0145913ad7'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_source(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('symlink_refused')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 200_000:
        raise ValueError('source_file_unexpected')
    raw = path.read_bytes()
    if sha(raw) != EXPECTED_SERVER:
        raise ValueError('source_fingerprint_changed')
    return raw


def fetch(name):
    url = (f'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
           f'{COMMIT}/manager-updater/{name}')
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(100_001)
    if sha(raw) != PINS[name]:
        raise ValueError('preparer_fingerprint_changed')
    return raw


def prepare_candidate(server, modules):
    originals = {name[:-3]: sys.modules.get(name[:-3]) for name in PINS}
    try:
        for name in PINS:
            module_name = name[:-3]
            module = types.ModuleType(module_name)
            sys.modules[module_name] = module
            exec(compile(modules[name], name, 'exec'), module.__dict__)
        output = sys.modules['server_graceful_shutdown_candidate'].prepare(
            server, EXPECTED_SERVER)
        return sha(output)
    finally:
        for name, previous in originals.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    raw = safe_source(SERVER)
    if not Path('/usr/sbin/lsof').is_file():
        raise ValueError('listener_inventory_unavailable')
    modules = {name: fetch(name) for name in PINS}
    candidate_sha = prepare_candidate(raw, modules)
    print('CONTROLE ARRET EN LECTURE SEULE : OK')
    print('Candidat serveur complet : ' + candidate_sha)
    print('Aucun fichier actif modifié. Aucune base ouverte. Aucun processus arrêté.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('CONTROLE REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'validation_failed'),
              file=sys.stderr)
        raise SystemExit(2)
