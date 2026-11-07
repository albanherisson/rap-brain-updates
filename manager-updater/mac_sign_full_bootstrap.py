#!/usr/bin/env python3
"""Prepare one installable, signed bootstrap transfer on the publisher Mac.

Reads only the three pinned active code files; never opens data, config or
Ollama, stops a process, installs code, publishes a release, or exports a key.
The existing local, fingerprinted Swift signer alone reads the private key.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


REPOSITORY = 'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
PINS_COMMIT = '35c03456b19b84946206bdb3d6abed2669a67ad2'
SOURCE_COMMIT = '6474488277a5507fd6cb48a1ff8f803680079aa7'
PINS_SHA256 = '58a0b3650a13f48003e90a6d4f34c764b2e9dfb8cfd421ad813b978d52f94ea1'
SWIFT_SHA256 = 'e585f5325f060dc2cc2877d533fd2b94b056dcb8bf5f6785c8ba7bf59ee4d6b1'
SIGNER_SHA256 = '3b5470b45487c765ed4d50cf53fdd27b9f44d828f31ca74f1f3b3fa9f4a611ef'
PUBLIC_BASE64 = 'LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY='
EXPECTED_CANDIDATES = (
    'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27',
    '79130fbb4c0404c271c83242718945258e0f0dd8616cad61fb890228672dd2e4',
    '43647e2449d4b7bfd6924502e728e8cf8bb5ebc0f7333d56d7e85bb0bbed1cb2',
)
OUTPUT_NAME = 'RapBrain_Bootstrap_Signe.zip'
ARCHIVE_NAME = 'guarded-1.zip'
ARCHIVE_URL = (REPOSITORY + 'main/manager-bootstrap/' + ARCHIVE_NAME)


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


def fetch_trusted_signer(folder):
    """Recover the same fingerprinted public signer after macOS clears /tmp."""
    url = REPOSITORY + SOURCE_COMMIT + '/publisher/publisher_key.swift'
    with urllib.request.urlopen(url, timeout=25) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('publisher_signer_source_changed')
        raw = response.read(50_001)
    if digest(raw) != SIGNER_SHA256:
        raise ValueError('publisher_signer_fingerprint_changed')
    target = folder / 'publisher_key.swift'
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
    return target


def get_inputs(folder):
    _, raw = fetch(PINS_COMMIT, 'mac_publisher_release_pins.json', PINS_SHA256)
    pins = json.loads(raw)
    if (type(pins) is not dict or pins.keys() != {'schema', 'commit', 'files'} or
            pins['schema'] != 'rapbrain-publisher-bootstrap-pins-v1' or
            pins['commit'] != SOURCE_COMMIT or type(pins['files']) is not dict or
            len(pins['files']) != 38 or
            not {'mac_final_readonly_probe.py', 'bootstrap_full_packager.py',
                 'bootstrap_full_release.py', 'creative_install_controller.py',
                 'owned_graceful_stop.py'} <= pins['files'].keys()):
        raise ValueError('publisher_source_inventory_changed')
    files = pins['files']
    if any(type(name) is not str or not name.endswith('.py') or '/' in name or
           type(sha) is not str or len(sha) != 64 or
           set(sha) - set('0123456789abcdef') for name, sha in files.items()):
        raise ValueError('publisher_source_inventory_invalid')
    with ThreadPoolExecutor(max_workers=4) as pool:
        modules = dict(pool.map(lambda item: fetch(SOURCE_COMMIT, *item),
                                files.items()))
    modules.update((fetch(SOURCE_COMMIT, 'verify_ed25519.swift', SWIFT_SHA256),))
    for name, content in modules.items():
        (folder / name).write_bytes(content)
    return modules


def create_signed_release(originals, runtime, public, signer, now):
    """Pure in-memory assembly; signer receives canonical bytes only."""
    from bootstrap_full_packager import assemble
    from bootstrap_full_release import (PRIMARY, RUNTIME_FILES,
                                        verify_full_bootstrap)
    from bootstrap_release import PUBLISHER_PIN
    from creative_release import canonical

    if (type(now) is not int or type(public) is not bytes or len(public) != 32 or
            digest(public) != PUBLISHER_PIN or not callable(signer)):
        raise ValueError('publisher_identity_invalid')
    archive, after, before = assemble(originals, runtime)
    payload = {'schema': 'rapbrain-guarded-bootstrap-v2', 'sequence': 1,
        'issued_at': now - 1, 'expires_at': now + 14 * 86400,
        'production_install_authorized': True, 'data_migrations': [],
        'validation': {'isolated_rollback': 'passed', 'macos_runtime': 'passed'},
        'archive_url': ARCHIVE_URL, 'archive_sha256': digest(archive),
        'archive_bytes': len(archive),
        'runtime_sha256': {name: after[name] for name in RUNTIME_FILES}}
    for kind, name in zip(('server', 'launcher', 'dashboard'), PRIMARY):
        payload['baseline_' + kind + '_sha256'] = before[name]
        payload['candidate_' + kind + '_sha256'] = after[name]
    signature = signer(canonical(payload))
    if type(signature) is not bytes or len(signature) != 64:
        raise ValueError('publisher_signature_invalid')
    signed = canonical({'signed_payload': payload,
        'signature_algorithm': 'Ed25519',
        'signature_base64': base64.b64encode(signature).decode('ascii'),
        'public_key_base64': base64.b64encode(public).decode('ascii')})
    verify_full_bootstrap(signed, archive, *(originals[name] for name in PRIMARY),
                          pinned_key=PUBLISHER_PIN, now=now)
    return signed, archive, after


def transfer_bundle(manifest, archive):
    if (type(manifest) is not bytes or type(archive) is not bytes or
            len(manifest) > 65536 or len(archive) > 2_000_000):
        raise ValueError('publisher_transfer_size')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, raw in (('manager-bootstrap/' + ARCHIVE_NAME, archive),
                          ('manager-bootstrap/manifest.json', manifest)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            bundle.writestr(info, raw)
    return buffer.getvalue()


def trusted_signer(home, folder):
    key = home / 'Library/Application Support/RapBrainManager/publisher_ed25519.key'
    swift = Path('/tmp/rapbrain_publisher_key.swift')
    if not key.exists():
        raise ValueError('publisher_private_key_missing')
    for path, size in ((key, 32),):
        info = path.lstat()
        if (path.is_symlink() or not stat.S_ISREG(info.st_mode) or
                info.st_uid != os.getuid() or not 0 < info.st_size <= size):
            raise ValueError('publisher_signer_or_key_unsafe')
    if key.stat().st_size != 32 or key.stat().st_mode & 0o077:
        raise ValueError('publisher_signer_or_key_changed')
    if not swift.exists():
        swift = fetch_trusted_signer(folder)
    info = swift.lstat()
    if (swift.is_symlink() or not stat.S_ISREG(info.st_mode) or
            info.st_uid != os.getuid() or not 0 < info.st_size <= 50_000 or
            digest(swift.read_bytes()) != SIGNER_SHA256):
        raise ValueError('publisher_signer_or_key_changed')

    def sign(message):
        path = folder / 'canonical-payload.json'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(message)
                stream.flush()
                os.fsync(stream.fileno())
            result = subprocess.run(['/usr/bin/swift', str(swift), 'sign', str(path)],
                                    capture_output=True, text=True, timeout=120,
                                    stdin=subprocess.DEVNULL)
        finally:
            path.unlink(missing_ok=True)
        if result.returncode or result.stderr or len(result.stdout) > 128:
            raise ValueError('publisher_signing_failed')
        return base64.b64decode(result.stdout.strip(), validate=True)
    return sign


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    home = Path.home()
    downloads = home / 'Downloads'
    if downloads.is_symlink() or not downloads.is_dir():
        raise ValueError('downloads_path_invalid')
    output = downloads / OUTPUT_NAME
    if os.path.lexists(output):
        raise ValueError('signed_transfer_already_exists')
    public = base64.b64decode(PUBLIC_BASE64, validate=True)
    with tempfile.TemporaryDirectory(prefix='rapbrain-publisher-', dir=downloads) as tmp:
        folder = Path(tmp)
        updater = folder / 'updater'
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
                raise ValueError('publisher_active_baseline_changed')
            from bootstrap_full_release import RUNTIME_FILES
            if not set(RUNTIME_FILES) <= modules.keys():
                raise ValueError('publisher_runtime_inventory_incomplete')
            runtime = {name: modules[name] for name in RUNTIME_FILES}
            signed, archive, after = create_signed_release(
                originals, runtime, public, trusted_signer(home, folder), int(time.time()))
            if tuple(after[name] for name in ('server.py', 'launch_manager.py',
                                               'dashboard_beta14.html')) != EXPECTED_CANDIDATES:
                raise ValueError('publisher_candidates_changed')
            # A second read catches edits during assembly without opening data.
            if any(probe.safe_source(path) != originals[name] for name, path in (
                    ('server.py', probe.SERVER), ('launch_manager.py', probe.LAUNCHER),
                    ('dashboard_beta14.html', probe.DASHBOARD))):
                raise ValueError('publisher_active_baseline_changed')
            transfer = transfer_bundle(signed, archive)
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(transfer)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                output.unlink(missing_ok=True)
                raise
        finally:
            sys.path.remove(str(updater))
    print('PAQUET COMPLET SIGNE : OK')
    print('Fichier à joindre dans ChatGPT : ' + str(output))
    print('Empreinte SHA256 : ' + digest(transfer))
    print('Aucune base, analyse, configuration Ollama ni clé privée incluse.')
    print('Aucune installation ni publication effectuée.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('SIGNATURE REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
