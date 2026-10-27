#!/usr/bin/env python3
"""Read-only Mac compatibility probe for the exact active Beta 14/server pair.

No source is uploaded, imported or executed. No database, Ollama config,
publisher key, live process, installed app file or backup is modified.
Pinned public patch preparers are fetched over HTTPS, verified by SHA-256,
then run only as text-to-text transformations in memory.
"""
import hashlib
from pathlib import Path
import stat
import sys
import urllib.request

COMMIT = 'd8f648f966cff3bbfc6f297e25df7547bf7092e6'
PINNED = {
    'server_lifetime_guard.py': 'aca364a27d7f778635ab3d6982f0f40680d840037eb5d4022d3f0c505d3b0f66',
    'beta14_launch_gate.py': 'af77102e3ba9dfa00f9b656d775ab715af9ab49d982219bcd9c95e2daa8c9fa1',
}
SERVER = Path.home() / 'Downloads' / 'rap-brain' / 'server.py'
LAUNCHER = (Path.home() / 'Downloads' / 'RapBrainManager_App_Beta14' /
            'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources' /
            'launch_manager.py')
EXPECTED_SERVER = '4380ab4fd97d727ced4521eb66b11004e21f9f15c0eafaee955f1f0145913ad7'
EXPECTED_LAUNCHER = '362ad3e1e3878cc49b90f76e212211e328e514b97c5a49b52921c0b4669964ba'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_read(path, expected):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('symlink_refused')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 200_000:
        raise ValueError('unexpected_source_file')
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError('source_fingerprint_changed')
    return raw


def pinned_module(name):
    url = (f'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
           f'{COMMIT}/manager-updater/{name}')
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(100_001)
    if digest(raw) != PINNED[name]:
        raise ValueError('patch_module_fingerprint_changed')
    scope = {'__name__': 'rapbrain_readonly_patch'}
    exec(compile(raw, name, 'exec'), scope)
    return scope


def probe(server, launcher, server_patch, launcher_patch):
    # The preparers parse and compile source only. They never import it.
    new_server = server_patch['prepare_admission'](server)
    new_launcher = launcher_patch['prepare'](launcher)
    return digest(new_server), digest(new_launcher)


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    server = safe_read(SERVER, EXPECTED_SERVER)
    launcher = safe_read(LAUNCHER, EXPECTED_LAUNCHER)
    prepared = probe(server, launcher, pinned_module('server_lifetime_guard.py'),
                     pinned_module('beta14_launch_gate.py'))
    print('CONTROLE EN LECTURE SEULE : OK')
    print('Serveur actif reconnu ; candidat compilé : ' + prepared[0])
    print('Lanceur Bêta 14 reconnu ; candidat compilé : ' + prepared[1])
    print('Aucun fichier actif modifié. Aucune base ouverte. Aucun serveur lancé.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('CONTROLE REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'validation_failed'),
              file=sys.stderr)
        raise SystemExit(2)
