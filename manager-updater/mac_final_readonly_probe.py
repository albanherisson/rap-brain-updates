#!/usr/bin/env python3
"""One consolidated read-only owner-Mac check before the first bootstrap.

Compiles the exact final candidates in memory and reports only coarse process
availability. No SQLite, Ollama config, private key, process stop, source edit
or server launch. Public preparers are fetched from one immutable commit and
verified against embedded SHA-256 digests before execution.
"""
import hashlib
from pathlib import Path
import stat
import subprocess
import sys
import types
import urllib.request


COMMIT = '36965d420a994b72bdd8d1b68c60b09409d4a0db'
PINS = {
    'server_lifetime_guard.py': 'ec30c3b0d2d957c2629696833da48ab68a90388e1f50f9c88240bf9046d3a9e6',
    'server_worker_resume_candidate.py': 'c498d630018898f9e1fe8984255acb1c7ccaadd223a9cdc118f530c3bb55fdad',
    'server_graceful_shutdown_candidate.py': 'b53a6beb78825b6305066547d66170add9c2b78af422dd0973a22ee9ceb1e7c4',
    'beta14_launch_gate.py': 'af77102e3ba9dfa00f9b656d775ab715af9ab49d982219bcd9c95e2daa8c9fa1',
    'beta14_runtime_token_candidate.py': '659d8bbf2b6e20432b696a6a6ec70dff63cd03b39af9eaac98f02905d4857a4e',
    'beta14_owned_identity_candidate.py': 'c66c6bfd6b720195ead6d102ce4e480b560fabfcb536fe5a867fc6c6d69fc31c',
    'recovery_start_guards.py': 'cfc3b573ae8b21a17f150aa7588549a9df6902601fe6d3e5dbb504e017a33086',
    'beta14_one_click_candidate.py': '50d99b296f3a8b30d21da5683ce9f916938033ed26dd82aafa67f5d66a66be42',
}
HOME = Path.home()
SERVER = HOME / 'Downloads' / 'rap-brain' / 'server.py'
RESOURCE = (HOME / 'Downloads' / 'RapBrainManager_App_Beta14' /
            'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources')
LAUNCHER = RESOURCE / 'launch_manager.py'
DASHBOARD = RESOURCE / 'dashboard_beta14.html'
EXPECTED = {
    SERVER: '4380ab4fd97d727ced4521eb66b11004e21f9f15c0eafaee955f1f0145913ad7',
    LAUNCHER: '362ad3e1e3878cc49b90f76e212211e328e514b97c5a49b52921c0b4669964ba',
    DASHBOARD: 'aa03ec8e0c11f117d26782276c13e31d79c44a7f70731f3728590acebb1d8d36',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_source(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('source_symlink_refused')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 200_000:
        raise ValueError('source_file_unexpected')
    raw = path.read_bytes()
    if sha(raw) != EXPECTED[path]:
        raise ValueError('source_fingerprint_changed')
    return raw


def fetch(name):
    url = (f'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
           f'{COMMIT}/manager-updater/{name}')
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(250_001)
    if sha(raw) != PINS[name]:
        raise ValueError('preparer_fingerprint_changed')
    return raw


def prepare_all(server, launcher, dashboard, modules):
    previous = {name[:-3]: sys.modules.get(name[:-3]) for name in PINS}
    try:
        for name in PINS:
            module = types.ModuleType(name[:-3])
            sys.modules[name[:-3]] = module
            exec(compile(modules[name], name, 'exec'), module.__dict__)
        guarded = sys.modules['recovery_start_guards'].prepare_server(server)
        app = sys.modules['beta14_one_click_candidate'].prepare_launcher(launcher)
        page = sys.modules['beta14_one_click_candidate'].prepare_dashboard(dashboard)
        return sha(guarded), sha(app), sha(page)
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def coarse_process_inventory(source, resource):
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,command='],
                            capture_output=True, text=True, timeout=8,
                            stdin=subprocess.DEVNULL)
    if (result.returncode != 0 or result.stderr or
            not 0 < len(result.stdout) <= 2_000_000):
        raise ValueError('process_inventory_unavailable')
    server_found = app_found = False
    for line in result.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4 or not all(part.isdecimal() for part in parts[:3]):
            raise ValueError('process_inventory_unexpected')
        command = parts[3]
        if (str(source / 'server.py') in command or
                ('python' in command.lower() and 'server.py' in command)):
            server_found = True
        if (str(resource / 'launch_manager.py') in command or
                'RapBrainManagerLegacy' in command or
                'Rap Brain Manager Beta 14.app' in command):
            app_found = True
    listener = subprocess.run(['/usr/sbin/lsof', '-nP', '-iTCP:8765',
                               '-sTCP:LISTEN', '-Fp'], capture_output=True,
                              text=True, timeout=8, stdin=subprocess.DEVNULL)
    if listener.returncode not in (0, 1) or listener.stderr:
        raise ValueError('listener_inventory_unavailable')
    return {'server_process_seen': server_found, 'manager_process_seen': app_found,
            'port_8765_listening': listener.returncode == 0}


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    sources = {path: safe_source(path) for path in EXPECTED}
    modules = {name: fetch(name) for name in PINS}
    server, launcher, dashboard = prepare_all(
        sources[SERVER], sources[LAUNCHER], sources[DASHBOARD], modules)
    census = coarse_process_inventory(SERVER.parent, RESOURCE)
    print('CONTROLE FINAL EN LECTURE SEULE : OK')
    print('Candidat serveur : ' + server)
    print('Candidat lanceur : ' + launcher)
    print('Candidat tableau de bord : ' + dashboard)
    print('Serveur en cours : ' + ('oui' if census['server_process_seen'] else 'non'))
    print('Manager en cours : ' + ('oui' if census['manager_process_seen'] else 'non'))
    print('Port Rap Brain occupé : ' + ('oui' if census['port_8765_listening'] else 'non'))
    print('Aucun fichier actif modifié. Aucune base ouverte. Aucun processus arrêté.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('CONTROLE REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'validation_failed'),
              file=sys.stderr)
        raise SystemExit(2)
