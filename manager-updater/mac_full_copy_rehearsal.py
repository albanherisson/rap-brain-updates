#!/usr/bin/env python3
"""Rehearse the complete guarded bootstrap on owner-Mac copies only.

No production key, archive publication, active SQLite/config read, or active
process signal. Public Python inputs are fetched from an immutable commit and
checked against one pinned manifest. Both runs use a private HOME and port.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request


REPOSITORY = 'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
PINS_COMMIT = '679ad9bd5e16363d1db05aa8a5096c4d4bc94155'
PINS_SHA256 = '9fef1e76afd869d5dd364bd99b080122cf04b830a1025c4cc0a1d2f58f83bbf3'
SWIFT_SHA256 = 'e585f5325f060dc2cc2877d533fd2b94b056dcb8bf5f6785c8ba7bf59ee4d6b1'
EXPECTED_CANDIDATES = (
    'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27',
    '79130fbb4c0404c271c83242718945258e0f0dd8616cad61fb890228672dd2e4',
    '43647e2449d4b7bfd6924502e728e8cf8bb5ebc0f7333d56d7e85bb0bbed1cb2',
)
SWIFT_SIGN = '''import Foundation
import CryptoKit
let bytes = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments.last!))
let key = Curve25519.Signing.PrivateKey()
print(key.publicKey.rawRepresentation.base64EncodedString())
print(try key.signature(for: bytes).base64EncodedString())
'''


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fetch(commit, name, expected):
    url = REPOSITORY + commit + '/manager-updater/' + name
    with urllib.request.urlopen(url, timeout=25) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('public_source_url_changed')
        raw = response.read(250_001)
    if digest(raw) != expected:
        raise ValueError('public_source_fingerprint_changed_' + name)
    if name.endswith('.py'):
        compile(raw, name, 'exec')
    return name, raw


def get_inputs(updater):
    _, raw = fetch(PINS_COMMIT, 'mac_full_copy_pins.json', PINS_SHA256)
    pins = json.loads(raw)
    if (type(pins) is not dict or pins.keys() != {'schema', 'commit', 'files'} or
            pins['schema'] != 'rapbrain-disposable-bootstrap-pins-v1' or
            pins['commit'] != '30a390751042a28680a3eb58d8d4773eeec79e1c' or
            type(pins['files']) is not dict or len(pins['files']) != 39 or
            not {'mac_final_readonly_probe.py', 'bootstrap_full_packager.py',
                 'offline_bootstrap_lifecycle.py'} <= pins['files'].keys()):
        raise ValueError('public_source_inventory_changed')
    files = pins['files']
    if any(type(name) is not str or not name.endswith('.py') or
           '/' in name or type(sha) is not str or len(sha) != 64
           for name, sha in files.items()):
        raise ValueError('public_source_inventory_invalid')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda item: fetch(pins['commit'], *item),
                                files.items()))
    results.append(fetch(pins['commit'], 'verify_ed25519.swift', SWIFT_SHA256))
    for name, content in results:
        (updater / name).write_bytes(content)
    return dict(results)


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    if port == 8765 or port < 1024:
        raise ValueError('isolated_port_unavailable')
    return port


def scoped_inspector(port):
    def inspect(source, resource):
        proc = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,command='],
                              capture_output=True, text=True, timeout=8)
        if proc.returncode or proc.stderr or len(proc.stdout) > 2_000_000:
            raise ValueError('disposable_process_inventory_unavailable')
        server = manager = False
        for line in proc.stdout.splitlines():
            fields = line.split(None, 3)
            if len(fields) != 4 or not all(s.isdecimal() for s in fields[:3]):
                raise ValueError('disposable_process_inventory_invalid')
            server |= str(source / 'server.py') in fields[3]
            manager |= str(resource / 'launch_manager.py') in fields[3]
        listener = subprocess.run(['/usr/sbin/lsof', '-nP', '-iTCP:' + str(port),
                                   '-sTCP:LISTEN', '-Fp'], capture_output=True,
                                  text=True, timeout=8)
        if listener.returncode not in (0, 1) or listener.stderr:
            raise ValueError('disposable_listener_inventory_unavailable')
        return {'server_process_seen': server, 'manager_process_seen': manager,
                'port_8765_listening': listener.returncode == 0}
    return inspect


def ephemeral_envelope(payload, folder):
    from creative_release import canonical, digest as sha
    message = folder / 'ephemeral-message.json'
    message.write_bytes(canonical(payload))
    result = subprocess.run(['/usr/bin/swift', '-e', SWIFT_SIGN, str(message)],
                            capture_output=True, text=True, timeout=120)
    message.unlink()
    if result.returncode or result.stderr or len(result.stdout) > 512:
        raise ValueError('ephemeral_signer_failed')
    lines = result.stdout.splitlines()
    if len(lines) != 2:
        raise ValueError('ephemeral_signature_invalid')
    public = base64.b64decode(lines[0], validate=True)
    signature = base64.b64decode(lines[1], validate=True)
    if len(public) != 32 or len(signature) != 64:
        raise ValueError('ephemeral_signature_invalid')
    return canonical({'signed_payload': payload, 'signature_algorithm': 'Ed25519',
                      'signature_base64': lines[1], 'public_key_base64': lines[0]}), sha(public)


def exercise(probe, originals, modules, workspace, *, failed_health):
    from app_bundle_backup import inventory
    from bootstrap_full_packager import assemble
    from bootstrap_full_release import PRIMARY, RUNTIME_FILES, verify_full_bootstrap
    from bootstrap_full_transaction import FullBootstrapTransaction
    from creative_release import digest as sha
    from isolated_runtime_stage import stage_python_closure
    from mac_disposable_app_signature_probe import copy_file_without_system_flags
    from offline_bootstrap_lifecycle import MacOfflineBootstrapLifecycle
    from owned_guarded_lifecycle import OwnedGuardedLifecycle

    home = workspace / 'home'
    downloads = home / 'Downloads'
    downloads.mkdir(parents=True, mode=0o700)
    source = downloads / 'rap-brain'
    staged = stage_python_closure(probe.SERVER.parent, source,
                                  originals['server.py'], sha(originals['server.py']))
    if not {'server.py', 'creative_engine.py'} <= staged.keys():
        raise ValueError('disposable_source_incomplete')
    data = source / 'data'
    data.mkdir(mode=0o700)
    with sqlite3.connect(data / 'rapbrain.sqlite3') as db:
        db.execute('CREATE TABLE probe_marker (value TEXT)')
        db.execute("INSERT INTO probe_marker VALUES ('disposable-only')")
    (data / 'ollama_model.json').write_bytes(b'{}')
    source_app = probe.RESOURCE.parents[1]
    app = downloads / 'RapBrainManager_App_Beta14' / source_app.name
    app.parent.mkdir(mode=0o700)
    shutil.copytree(source_app, app, copy_function=copy_file_without_system_flags)
    original_app = inventory(app)
    original_engine = (source / 'creative_engine.py').read_bytes()
    original_config = (data / 'ollama_model.json').read_bytes()
    launcher = app / 'Contents' / 'Resources' / 'launch_manager.py'
    runtime = {name: modules[name] for name in RUNTIME_FILES}
    archive, after, before = assemble(originals, runtime)
    if tuple(after[name] for name in PRIMARY) != EXPECTED_CANDIDATES:
        raise ValueError('assembled_candidate_changed')
    port = free_port()
    state = downloads / 'RapBrainManagerBackups' / 'secure-update'
    state.mkdir(parents=True, mode=0o700)
    now = int(time.time())
    payload = {'schema': 'rapbrain-guarded-bootstrap-v2', 'sequence': 1,
        'issued_at': now - 1, 'expires_at': now + 3600,
        'production_install_authorized': True, 'data_migrations': [],
        'validation': {'isolated_rollback': 'passed', 'macos_runtime': 'passed'},
        'archive_url': 'https://albanherisson.github.io/rap-brain-updates/manager-bootstrap/disposable-only.zip',
        'archive_sha256': sha(archive), 'archive_bytes': len(archive),
        'runtime_sha256': {name: after[name] for name in RUNTIME_FILES}}
    for kind, name in zip(('server', 'launcher', 'dashboard'), PRIMARY):
        payload['baseline_' + kind + '_sha256'] = before[name]
        payload['candidate_' + kind + '_sha256'] = after[name]
    signed, ephemeral_pin = ephemeral_envelope(payload, workspace)
    verify_full_bootstrap(signed, archive, *(originals[name] for name in PRIMARY),
                          pinned_key=ephemeral_pin)

    class ForcedFailedHealth(OwnedGuardedLifecycle):
        def start_and_check(self):
            healthy = super().start_and_check()
            if not healthy:
                raise ValueError('disposable_candidate_unhealthy')
            return False

    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', LANG='C', HOME=str(home),
                      RAP_BRAIN_PORT=str(port), PYTHONDONTWRITEBYTECODE='1')
    try:
        lifecycle = MacOfflineBootstrapLifecycle(
            source, launcher, state, payload, port=port,
            inspector=scoped_inspector(port),
            candidate_factory=ForcedFailedHealth if failed_health else OwnedGuardedLifecycle)
        result = FullBootstrapTransaction(source, launcher, state, lifecycle,
                                          pinned_key=ephemeral_pin).install(signed, archive)
    finally:
        os.environ.clear()
        os.environ.update(previous)
    expected = 'restored_stopped' if failed_health else 'committed'
    if result['state'] != expected or result['installation_performed'] is not (not failed_health):
        raise ValueError('disposable_transaction_result_invalid')
    if (data / 'ollama_model.json').read_bytes() != original_config:
        raise ValueError('disposable_config_changed')
    with sqlite3.connect((data / 'rapbrain.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        if (db.execute('PRAGMA quick_check').fetchone() != ('ok',) or
                db.execute('SELECT value FROM probe_marker').fetchone() != ('disposable-only',)):
            raise ValueError('disposable_database_changed')
    if (source / 'creative_engine.py').read_bytes() != original_engine:
        raise ValueError('disposable_engine_changed')
    if failed_health:
        if inventory(app) != original_app or any((launcher.parent / n).exists()
                                                   for n in RUNTIME_FILES):
            raise ValueError('disposable_rollback_changed')
    else:
        if any(sha((source / n if n == 'server.py' else launcher.parent / n).read_bytes())
               != after[n] for n in after):
            raise ValueError('disposable_commit_changed')
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)],
                   capture_output=True, check=True, timeout=90)
    if (state / 'maintenance.ticket').exists() or scoped_inspector(port)(source, launcher.parent)['port_8765_listening']:
        raise ValueError('disposable_process_or_marker_remaining')


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    downloads = Path.home() / 'Downloads'
    if downloads.is_symlink() or not downloads.is_dir():
        raise ValueError('downloads_path_invalid')
    workspace = Path(tempfile.mkdtemp(prefix='rapbrain-full-copy-', dir=downloads))
    original_home = Path.home()
    try:
        updater = workspace / 'updater'
        updater.mkdir(mode=0o700)
        modules = get_inputs(updater)
        sys.path.insert(0, str(updater))
        try:
            probe = importlib.import_module('mac_final_readonly_probe')
            originals = {name: probe.safe_source(path) for name, path in (
                ('server.py', probe.SERVER), ('launch_manager.py', probe.LAUNCHER),
                ('dashboard_beta14.html', probe.DASHBOARD))}
            if probe.prepare_all(originals['server.py'], originals['launch_manager.py'],
                                 originals['dashboard_beta14.html'],
                                 {name: modules[name] for name in probe.PINS}) != EXPECTED_CANDIDATES:
                raise ValueError('owner_candidate_changed')
            source_app = probe.RESOURCE.parents[1]
            from app_bundle_backup import inventory
            original_app = inventory(source_app)
            for name, failure in (('commit', False), ('rollback', True)):
                location = workspace / name
                location.mkdir(mode=0o700)
                exercise(probe, originals, modules, location, failed_health=failure)
            if (inventory(source_app) != original_app or
                    any(probe.safe_source(path) != originals[name] for name, path in (
                        ('server.py', probe.SERVER), ('launch_manager.py', probe.LAUNCHER),
                        ('dashboard_beta14.html', probe.DASHBOARD)))):
                raise ValueError('owner_active_files_changed')
        finally:
            sys.path.remove(str(updater))
    except BaseException:
        # Preserve the disposable workspace for inspection if an owned process
        # or recovery marker could still be present; never kill by PID.
        print('TEST REFUSE : copies conservées dans ' + str(workspace), file=sys.stderr)
        raise
    else:
        shutil.rmtree(workspace)
        print('TEST COMPLET SUR COPIES : OK')
        print('Installation, santé HTTP, signature et retour arrière vérifiés sur copies.')
        print('Rap Brain actif, bibliothèque, SQLite et configuration Ollama inchangés.')
        print('Clé privée de publication non utilisée. Aucune installation réelle.')
    finally:
        if Path.home() != original_home:
            raise ValueError('home_environment_not_restored')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('TEST REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'validation_failed'),
              file=sys.stderr)
        raise SystemExit(2)
