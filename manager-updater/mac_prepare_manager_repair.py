#!/usr/bin/env python3
"""Owner-Mac preparation of one signed, copy-tested Finder repair app.

The publisher seed stays local. This prepares a separate app under Downloads;
it does not replace Rap Brain, its Manager, or any live data.
"""
import base64
import hashlib
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


SOURCE_REF = 'f3809f896363f44e242b3d3a5ce27f9c0fac7e7e'
SOURCE_MANIFEST_SHA256 = 'abff9b78b270a58d31940bef2d7a0ffebe908fd5c31e97124bae784dd3d2a7f7'
CAPABILITY_REF = '19d84a4db0713a658265df3358a68c1adc6388be'
CAPABILITY_SHA256 = '963ca5733de48d7d336b1c214a0b8f308aa582aa3484a5ae51769daafe0cf8a7'
BASE = 'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
OUTPUT = 'Réparer les mises à jour Rap Brain.app'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('download_redirect_refused')


def fetch(url, limit):
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(url, headers={
            'Accept-Encoding': 'identity'}), timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('download_origin_changed')
        result = response.read(limit + 1)
    if not 0 < len(result) <= limit:
        raise ValueError('download_size_invalid')
    return result


def zip_files(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, data)
    return stream.getvalue()


def prepare(home, *, downloader=fetch):
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    home = Path(home).resolve()
    output = home / 'Downloads' / OUTPUT
    if output.exists() or output.is_symlink():
        raise ValueError('repair_app_already_exists')
    manifest_url = BASE + SOURCE_REF + '/manager-repair/source-hashes.json'
    raw = downloader(manifest_url, 10_000)
    if digest(raw) != SOURCE_MANIFEST_SHA256:
        raise ValueError('source_inventory_changed')
    pins = json.loads(raw)
    if (type(pins) is not dict or not 25 <= len(pins) <= 50 or
            any(type(n) is not str or not n.endswith(('.py', '.sh', '.swift')) or
                '/' in n or n.startswith('.') or type(h) is not str or len(h) != 64
                for n, h in pins.items())):
        raise ValueError('source_inventory_invalid')
    capability_url = BASE + CAPABILITY_REF + '/manager-capability/capability-1.zip'
    archive = downloader(capability_url, 2_000_000)
    if digest(archive) != CAPABILITY_SHA256:
        raise ValueError('published_capability_changed')
    resources = (home / 'Downloads/RapBrainManager_App_Beta14' /
                 'Rap Brain Manager Beta 14.app/Contents/Resources')
    source = home / 'Downloads/rap-brain'
    state = home / 'Downloads/RapBrainManagerBackups/secure-update'
    app = resources.parents[1]
    launcher = resources / 'launch_manager.py'
    with tempfile.TemporaryDirectory(prefix='rapbrain-repair-build-',
                                     dir=home / 'Downloads') as temporary:
        root = Path(temporary)
        for name, expected in pins.items():
            code = downloader(BASE + SOURCE_REF + '/manager-updater/' + name,
                              1_000_000)
            if digest(code) != expected:
                raise ValueError('source_hash_changed_' + name)
            (root / name).write_bytes(code)
        sys.path.insert(0, str(root))
        from build_manager_handoff_repair import build as build_candidate
        from build_manager_repair_app import build as build_finder
        from manager_helper_inventory import HELPER_FILES
        from manager_helper_release import verify_staged
        from manager_repair_release import (ARCHIVE, FILES, LAUNCHER,
            NATIVE_SOURCE, OLD_HELPER, SERVER, verify_release)
        from manager_repair_rehearsal import rehearse_on_copy
        from mac_sign_manager_capability import envelope
        from creative_release import digest as release_digest
        from creative_transaction import safe_path
        from mac_offline_bootstrap_gate import verify_unchanged_app
        if not (safe_path(launcher).read_bytes() and
                release_digest(launcher.read_bytes()) == LAUNCHER and
                release_digest(safe_path(resources / 'RapBrainManagerNative.swift').read_bytes()) == NATIVE_SOURCE and
                release_digest(safe_path(source / 'server.py').read_bytes()) == SERVER):
            raise ValueError('active_manager_baseline_changed')
        verify_unchanged_app(app, source, launcher, inspector=lambda *_: {
            'server_process_seen': False, 'manager_process_seen': False,
            'port_8765_listening': False})
        old = verify_staged(state)
        from strict_json import parse_signed_json
        old_signed = safe_path(old / 'signed-manifest.json').read_bytes()
        if parse_signed_json(old_signed)['signed_payload']['archive_sha256'] != OLD_HELPER:
            raise ValueError('active_helper_baseline_changed')
        candidate_path = root / 'capability-1.zip'
        candidate_path.write_bytes(archive)
        files = build_candidate(candidate_path, resources / 'RapBrainManagerNative.swift')
        package = zip_files(files)
        now = int(time.time())
        validation = {'macos_copy_install': 'passed', 'rollback': 'passed',
                      'runtime': 'passed'}
        with zipfile.ZipFile(io.BytesIO(files['helper.zip'])) as helper:
            helper_hashes = {name: digest(helper.read('helper/' + name))
                             for name in HELPER_FILES}
        key = home / 'Library/Application Support/RapBrainManager/publisher_ed25519.key'
        helper_payload = {'schema': 'rapbrain-manager-helper-v1',
            'sequence': 2, 'issued_at': now - 1, 'expires_at': now + 14 * 86400,
            'production_install_authorized': True, 'validation': validation,
            'files': helper_hashes, 'archive_sha256': digest(files['helper.zip']),
            'archive_bytes': len(files['helper.zip'])}
        helper_signed = envelope(helper_payload, key)
        payload = {'schema': 'rapbrain-manager-repair-v1', 'sequence': 2,
            'issued_at': now - 1, 'expires_at': now + 14 * 86400,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': validation, 'baseline_launcher_sha256': LAUNCHER,
            'baseline_native_source_sha256': NATIVE_SOURCE,
            'baseline_helper_sha256': OLD_HELPER,
            'required_server_sha256': SERVER,
            'archive_url': ARCHIVE, 'archive_sha256': digest(package),
            'archive_bytes': len(package),
            'files': {name: digest(files[name]) for name in FILES},
            'helper_manifest_base64': base64.b64encode(helper_signed).decode()}
        signed = envelope(payload, key)
        verify_release(signed, package)
        report = rehearse_on_copy(source, launcher, state, signed, package)
        if report != {'state': 'passed', 'active_files_modified': False,
                      'live_database_opened': False,
                      'live_configuration_opened': False}:
            raise ValueError('mac_copy_rehearsal_failed')
        candidate_app = root / OUTPUT
        build_finder(candidate_app, release=signed, archive=package, source=root)
        if output.exists() or output.is_symlink():
            raise ValueError('repair_app_destination_changed')
        os.rename(candidate_app, output)
    return output


def main():
    result = prepare(Path.home())
    print('REPARATION PREPAREE : OK')
    print('Application Finder : ' + str(result))
    print('Aucun fichier Rap Brain actif modifié. Ouvre cette application dans Finder après avoir fermé Rap Brain et le Manager.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('PREPARATION REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
