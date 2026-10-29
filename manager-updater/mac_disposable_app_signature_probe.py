#!/usr/bin/env python3
"""Owner-Mac app signing and rollback rehearsal on a disposable copy only.

Reads exact pinned source and app files. Never imports the owner's server,
opens SQLite/config, stops a process, or edits the original app. No private
data is sent: only pinned public preparer code is downloaded from GitHub.
"""
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import urllib.request


PROBE_URL = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
             'b009fa8ae1783f869196e26a534b1f62322d4a18/'
             'manager-updater/mac_final_readonly_probe.py')
PROBE_SHA256 = '41ab50fd232d92e6ec1a803b517efbc9cd331eef687eeda601c05c35dfcf746f'
EXPECTED_CANDIDATES = (
    'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27',
    '79130fbb4c0404c271c83242718945258e0f0dd8616cad61fb890228672dd2e4',
    '43647e2449d4b7bfd6924502e728e8cf8bb5ebc0f7333d56d7e85bb0bbed1cb2',
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load_pinned_probe():
    with urllib.request.urlopen(PROBE_URL, timeout=20) as response:
        raw = response.read(250001)
    if digest(raw) != PROBE_SHA256:
        raise ValueError('public_probe_fingerprint_changed')
    module = types.ModuleType('pinned_final_readonly_probe')
    exec(compile(raw, 'mac_final_readonly_probe.py', 'exec'), module.__dict__)
    return module


def inventory(app):
    app = Path(app)
    result = {}
    total = 0
    for base, dirs, files in os.walk(app, followlinks=False):
        for name in dirs + files:
            path = Path(base) / name
            info = path.lstat()
            if path.is_symlink() or not (stat.S_ISREG(info.st_mode) or
                                        stat.S_ISDIR(info.st_mode)):
                raise ValueError('app_entry_unsafe')
            if stat.S_ISDIR(info.st_mode):
                continue
            raw = path.read_bytes()
            total += len(raw)
            if len(result) >= 1000 or total > 100_000_000:
                raise ValueError('app_copy_size_limit')
            result[path.relative_to(app).as_posix()] = (digest(raw),
                stat.S_IMODE(info.st_mode))
    if not result:
        raise ValueError('app_copy_empty')
    return result


def codesign(app, *, replace=False):
    if replace:
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-',
                        str(app)], check=True, capture_output=True, timeout=90,
                       stdin=subprocess.DEVNULL)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                    str(app)], check=True, capture_output=True, timeout=90,
                   stdin=subprocess.DEVNULL)


def run():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    probe = load_pinned_probe()
    server = probe.safe_source(probe.SERVER)
    launcher = probe.safe_source(probe.LAUNCHER)
    dashboard = probe.safe_source(probe.DASHBOARD)
    modules = {name: probe.fetch(name) for name in probe.PINS}
    hashes = probe.prepare_all(server, launcher, dashboard, modules)
    if hashes != EXPECTED_CANDIDATES:
        raise ValueError('candidate_fingerprint_changed')
    # The preparers have already been pinned, compiled, and hash-checked.
    # Recreate their exact output only in memory for writing into a copy.
    previous = {name[:-3]: sys.modules.get(name[:-3]) for name in probe.PINS}
    try:
        for name in probe.PINS:
            module = types.ModuleType(name[:-3])
            sys.modules[name[:-3]] = module
            exec(compile(modules[name], name, 'exec'), module.__dict__)
        candidate_launcher = sys.modules['beta14_one_click_candidate'].prepare_launcher(launcher)
        candidate_dashboard = sys.modules['beta14_one_click_candidate'].prepare_dashboard(dashboard)
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
    if (digest(candidate_launcher), digest(candidate_dashboard)) != hashes[1:]:
        raise ValueError('candidate_bytes_changed')
    source_app = probe.RESOURCE.parents[1]
    if source_app.suffix != '.app' or source_app.is_symlink():
        raise ValueError('app_path_unexpected')
    original = inventory(source_app)
    with tempfile.TemporaryDirectory(prefix='rapbrain-app-signature-copy-') as temp:
        folder = Path(temp)
        app = folder / 'candidate.app'
        backup = folder / 'backup.app'
        shutil.copytree(source_app, app, symlinks=True)
        if inventory(app) != original:
            raise ValueError('app_copy_changed')
        codesign(app)
        shutil.copytree(app, backup, symlinks=True)
        if inventory(backup) != original:
            raise ValueError('app_backup_changed')
        resources = app / 'Contents' / 'Resources'
        (resources / 'launch_manager.py').write_bytes(candidate_launcher)
        (resources / 'dashboard_beta14.html').write_bytes(candidate_dashboard)
        codesign(app, replace=True)
        if (digest((resources / 'launch_manager.py').read_bytes()) != hashes[1] or
                digest((resources / 'dashboard_beta14.html').read_bytes()) != hashes[2]):
            raise ValueError('signed_candidate_changed')
        shutil.rmtree(app)
        shutil.copytree(backup, app, symlinks=True)
        if inventory(app) != original:
            raise ValueError('copy_rollback_changed')
        codesign(app)
    if inventory(source_app) != original:
        raise ValueError('original_app_changed')
    if digest(probe.SERVER.read_bytes()) != probe.EXPECTED[probe.SERVER]:
        raise ValueError('original_server_changed')
    print('CONTROLE SIGNATURE SUR COPIE : OK')
    print('Application candidate signée puis copie d’origine restaurée et vérifiée.')
    print('Aucun fichier actif modifié. Aucune base ouverte. Aucun processus arrêté.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print('CONTROLE REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'validation_failed'),
              file=sys.stderr)
        raise SystemExit(2)
