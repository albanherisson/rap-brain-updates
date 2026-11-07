#!/usr/bin/env python3
"""Compile the worker-gated candidate in memory on the owner's Mac, read-only.

Never imports or executes the active server. No database, app or process access.
Both public preparers are fetched at a fixed commit and checked by SHA-256.
"""
import hashlib
from pathlib import Path
import stat
import sys
import types
import urllib.request

COMMIT = 'bb5d3f8ea6f0a9cd71f344c4969e9b22c4b1de6a'
MODULES = {
    'server_lifetime_guard.py': 'ec30c3b0d2d957c2629696833da48ab68a90388e1f50f9c88240bf9046d3a9e6',
    'server_worker_activity_candidate.py': 'c48aa097664129daa621395123726a5d6a1dad935af33bdcb6118b887569addc',
}
SERVER = Path.home() / 'Downloads' / 'rap-brain' / 'server.py'
EXPECTED = '4380ab4fd97d727ced4521eb66b11004e21f9f15c0eafaee955f1f0145913ad7'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def source():
    if any(part.is_symlink() for part in (SERVER, *SERVER.parents)):
        raise ValueError('symlink_refused')
    info = SERVER.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 200_000:
        raise ValueError('unexpected_server_file')
    raw = SERVER.read_bytes()
    if sha(raw) != EXPECTED:
        raise ValueError('server_fingerprint_changed')
    return raw


def fetch(name):
    url = (f'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
           f'{COMMIT}/manager-updater/{name}')
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(100_001)
    if sha(raw) != MODULES[name]:
        raise ValueError('patch_fingerprint_changed')
    return raw


def compile_candidate(raw, base, worker, expected_sha256=EXPECTED):
    # Only pinned public transformation code runs; the private source is
    # passed as bytes and compiled, never imported or executed.
    module = types.ModuleType('server_lifetime_guard')
    exec(compile(base, 'server_lifetime_guard.py', 'exec'), module.__dict__)
    previous = sys.modules.get('server_lifetime_guard')
    sys.modules['server_lifetime_guard'] = module
    try:
        scope = {'__name__': 'rapbrain_readonly_worker_patch'}
        exec(compile(worker, 'server_worker_activity_candidate.py', 'exec'), scope)
        return sha(scope['prepare_worker_activity'](raw, expected_sha256))
    finally:
        if previous is None:
            sys.modules.pop('server_lifetime_guard', None)
        else:
            sys.modules['server_lifetime_guard'] = previous


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    raw = source()
    candidate = compile_candidate(raw, fetch('server_lifetime_guard.py'),
                                  fetch('server_worker_activity_candidate.py'))
    print('CONTROLE WORKER EN LECTURE SEULE : OK')
    print('Serveur actif reconnu ; nouveau candidat compilé : ' + candidate)
    print('Aucun fichier actif modifié. Aucune base ouverte. Aucun serveur lancé.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('CONTROLE REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'validation_failed'),
              file=sys.stderr)
        raise SystemExit(2)
