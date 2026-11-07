#!/usr/bin/env python3
"""Owner Mac compatibility check for the combined server and Beta 14 copies.

Only reads two pinned source files and compiles transformed candidates in
memory. No database/config/key, process control, or installation.
"""
import hashlib
from pathlib import Path
import stat
import sys
import types
import urllib.request

COMMIT = '27ef4331fe6f49044e264e9c911b82594a4b0a1d'
PINS = {
    'server_lifetime_guard.py': 'ec30c3b0d2d957c2629696833da48ab68a90388e1f50f9c88240bf9046d3a9e6',
    'server_worker_resume_candidate.py': 'c498d630018898f9e1fe8984255acb1c7ccaadd223a9cdc118f530c3bb55fdad',
    'beta14_launch_gate.py': 'af77102e3ba9dfa00f9b656d775ab715af9ab49d982219bcd9c95e2daa8c9fa1',
    'beta14_runtime_token_candidate.py': '659d8bbf2b6e20432b696a6a6ec70dff63cd03b39af9eaac98f02905d4857a4e',
}
HOME = Path.home()
SERVER = HOME / 'Downloads' / 'rap-brain' / 'server.py'
LAUNCHER = (HOME / 'Downloads' / 'RapBrainManager_App_Beta14' /
            'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources' / 'launch_manager.py')
EXPECTED_SERVER = '4380ab4fd97d727ced4521eb66b11004e21f9f15c0eafaee955f1f0145913ad7'
EXPECTED_LAUNCHER = '362ad3e1e3878cc49b90f76e212211e328e514b97c5a49b52921c0b4669964ba'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_source(path, expected):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('symlink_refused')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 200_000:
        raise ValueError('source_file_unexpected')
    raw = path.read_bytes()
    if sha(raw) != expected:
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


def prepare_pair(server, launcher, modules, *,
                 expected_server=EXPECTED_SERVER, expected_launcher=EXPECTED_LAUNCHER):
    outputs = []
    for base_name, next_name, data in (
            ('server_lifetime_guard.py', 'server_worker_resume_candidate.py', server),
            ('beta14_launch_gate.py', 'beta14_runtime_token_candidate.py', launcher)):
        base_module_name = base_name[:-3]
        base = types.ModuleType(base_module_name)
        exec(compile(modules[base_name], base_name, 'exec'), base.__dict__)
        previous = sys.modules.get(base_module_name)
        sys.modules[base_module_name] = base
        try:
            scope = {'__name__': 'rapbrain_readonly_preparer'}
            exec(compile(modules[next_name], next_name, 'exec'), scope)
            outputs.append(sha(scope['prepare_worker_activity'](data, expected_server)
                               if base_name.startswith('server') else
                               scope['prepare'](data, expected_launcher)))
        finally:
            if previous is None:
                sys.modules.pop(base_module_name, None)
            else:
                sys.modules[base_module_name] = previous
    return outputs


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    server = safe_source(SERVER, EXPECTED_SERVER)
    launcher = safe_source(LAUNCHER, EXPECTED_LAUNCHER)
    modules = {name: fetch(name) for name in PINS}
    server_hash, launcher_hash = prepare_pair(server, launcher, modules)
    print('CONTROLE COMBINE EN LECTURE SEULE : OK')
    print('Candidat serveur : ' + server_hash)
    print('Candidat lanceur Bêta 14 : ' + launcher_hash)
    print('Aucun fichier actif modifié. Aucune base ouverte. Aucun serveur lancé.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('CONTROLE REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'validation_failed'),
              file=sys.stderr)
        raise SystemExit(2)
