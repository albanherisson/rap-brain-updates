#!/usr/bin/env python3
"""Run the pinned guarded candidate inside a disposable Mac home only.

The active server and Manager remain running. Never copies data/config,
imports active server code, or sends a signal to an existing process.
"""
import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
import types
import urllib.request


COMMIT = '85ba278a67892bacd3452ddd6d1f367e783954a1'
MODULES = {
    'isolated_runtime_lab.py': '80e1aea3ba7e3c62ea34fb1f3bef10d601092d244445fc011883056a9d663a08',
    'isolated_runtime_stage.py': '5f8ee3370cfa9e112efcf682391e396560be21d6bc7b1fa1593465cc60f8bf30',
    'isolated_runtime_runner.py': '117613b8742de2e0c8b991da75c8f889a406e1d64744e145a6aa23290593ba18',
    'isolated_runtime_port.py': 'acb9692cd1b4f518df6d0e8d1f3a94079a4af59d0f4e16089ea2ff91225dd6ab',
    'creative_release.py': 'b50195f6665baefd1838f5aec2e750ed33504804d80c6f09bd493aa20ce779a9',
    'creative_transaction.py': '669f5c0b6c2def2d3fec19b8e8a07d25466ed96c59020f73fa0943a7a313beb8',
    'authenticated_runtime_client.py': '64b8766d91bc34e903e965bc92a8c75a61e3e2d5b6773c7d6708538ba549092d',
    'strict_json.py': '2a65d68caa032c9d561efd4c3c881e54d15e63ba62b8e798fbf613bd94bde183',
    'ed25519_runtime.py': 'b23b50134ebc1177c17dcece765cdf8cb689e5139eca5518d0444068e6ec4ca1',
}
FINAL_URL = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
             'b009fa8ae1783f869196e26a534b1f62322d4a18/'
             'manager-updater/mac_final_readonly_probe.py')
FINAL_SHA256 = '41ab50fd232d92e6ec1a803b517efbc9cd331eef687eeda601c05c35dfcf746f'
EXPECTED_CANDIDATE = 'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27'


def fetch(url, expected):
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(250_001)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('public_module_changed')
    compile(raw, url.rsplit('/', 1)[-1], 'exec')
    return raw


def pinned_candidate(probe, raw):
    modules = {name: probe.fetch(name) for name in probe.PINS}
    if probe.prepare_all(raw, probe.safe_source(probe.LAUNCHER),
                         probe.safe_source(probe.DASHBOARD), modules)[0] != EXPECTED_CANDIDATE:
        raise ValueError('server_candidate_changed')
    previous = {name[:-3]: sys.modules.get(name[:-3]) for name in probe.PINS}
    try:
        for name in probe.PINS:
            module = types.ModuleType(name[:-3])
            sys.modules[name[:-3]] = module
            exec(compile(modules[name], name, 'exec'), module.__dict__)
        candidate = sys.modules['recovery_start_guards'].prepare_server(raw)
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
    if hashlib.sha256(candidate).hexdigest() != EXPECTED_CANDIDATE:
        raise ValueError('server_candidate_changed')
    return candidate


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    root = Path.home() / 'Downloads'
    if root.is_symlink() or not root.is_dir():
        raise ValueError('downloads_path_invalid')
    final = types.ModuleType('pinned_final_readonly_probe')
    exec(fetch(FINAL_URL, FINAL_SHA256), final.__dict__)
    original = final.safe_source(final.SERVER)
    candidate = pinned_candidate(final, original)
    with tempfile.TemporaryDirectory(prefix='rapbrain-runtime-probe-', dir=root) as temporary:
        directory = Path(temporary)
        updater = directory / 'updater'
        updater.mkdir(mode=0o700)
        for name, expected in MODULES.items():
            url = f'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/{COMMIT}/manager-updater/{name}'
            (updater / name).write_bytes(fetch(url, expected))
        sys.path.insert(0, str(updater))
        try:
            lab = importlib.import_module('isolated_runtime_lab')
            work = directory / 'work'
            work.mkdir(mode=0o700)
            report = lab.rehearse(final.SERVER.parent, candidate, final.EXPECTED[final.SERVER],
                                  EXPECTED_CANDIDATE, workspace=work)
        finally:
            sys.path.remove(str(updater))
    if final.safe_source(final.SERVER) != original:
        raise ValueError('active_server_changed')
    print('TEST SERVEUR ISOLE : OK')
    print('Etat HTTP verifie ; modules copies : ' + str(report['modules_staged']))
    print('Serveur actif inchange. Aucune base ni configuration active ouverte.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('TEST ISOLE REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'validation_failed'),
              file=sys.stderr)
        raise SystemExit(2)
