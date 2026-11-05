#!/usr/bin/env python3
"""Owner-Mac signing of the narrow, copy-tested Manager startup repair.

The pinned earlier signed repair supplies the exact native and helper bytes;
only the launcher receipt reader changes. Nothing installed is modified here.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import urllib.request
import zipfile


BASE = 'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
OLD_SOURCE = 'c73c4b318f468eb077b3f013556ffa7368d804ba'
OLD_SOURCE_HASH = '352377006e6199190a80bd7bbadbb5d5c949371c40d75a46c4a47048beb13028'
SIGNED_REF = '9b6dab38ec7d37344519857861ed077f457a1d93'
PREVIOUS_MANIFEST_HASH = 'f1670aa75be406ff90099f4c8234ecb86c648fc4aa1be71a58afa98521d50841'
PREVIOUS_ARCHIVE_HASH = 'bd67ee13d07e154698a30a81a041c45a71042f4c173b09f93ab346f0d6839b06'
# Filled with one immutable commit and its independently reviewed source list
# before this script is published for execution on the owner Mac.
NEW_SOURCE = '5190fa9891eaafed887c33c644f80804b13d41ff'
NEW_HASHES = {
    'manager_repair_release.py': '5377438bce3132b8c4fb88116dbbfa37f317ee90fc494335ec8110492f28ecc9',
    'manager_repair_transaction.py': '628d421353fb821a986d2b504a5c7e301ef4f9f9b1da3a4d147e96c05708a485',
    'manager_repair_rehearsal.py': '6951e232138898d6cc51e5e04c68b68e193b8760d65e900ccc1ad4245e19f647',
    'manager_repair_installer.py': '36b8f96cee255781a2711a507c3708ec51b552497ab44f362a8ec82a90ffc89f',
    'build_manager_repair_app.py': 'e2a2ff122f8034419c711f70c294b9d26746e8937511de06c77f53eb617f2b85',
    'manager_postcommit_start_candidate.py': 'eb64a3b52f0353b3bb161ff5e077413600dad780548260ec6766896c11263fd1',
}
OUTPUT = 'Réparer le démarrage Rap Brain.app'
PUBLIC = 'RapBrain_Manager_Postcommit_Publication.zip'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def download(url, limit):
    if not url.startswith(BASE):
        raise ValueError('unexpected_download_origin')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            raise ValueError('redirect_refused')
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(url, headers={'Accept-Encoding': 'identity'}),
                     timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('download_changed')
        raw = response.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise ValueError('download_size')
    return raw


def packed(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, data)
    return output.getvalue()


def prepare(home, *, fetch=download):
    if sys.platform != 'darwin' or len(NEW_SOURCE) != 40 or not NEW_HASHES:
        raise ValueError('mac_or_reviewed_source_required')
    home = Path(home).resolve()
    out = home / 'Downloads' / OUTPUT
    public = home / 'Downloads' / PUBLIC
    if any(os.path.lexists(p) for p in (out, public)):
        raise ValueError('publication_already_exists')
    raw_pins = fetch(BASE + OLD_SOURCE + '/manager-repair/source-hashes.json', 10000)
    if digest(raw_pins) != OLD_SOURCE_HASH:
        raise ValueError('old_source_list_changed')
    pins = json.loads(raw_pins)
    signed_old = fetch(BASE + SIGNED_REF + '/manager-repair/manifest.json', 65536)
    archive_old = fetch(BASE + SIGNED_REF + '/manager-repair/repair-1.zip', 2000000)
    if (digest(signed_old) != PREVIOUS_MANIFEST_HASH or
            digest(archive_old) != PREVIOUS_ARCHIVE_HASH):
        raise ValueError('previous_signed_repair_changed')
    with tempfile.TemporaryDirectory(prefix='rapbrain-postcommit-build-',
                                     dir=home / 'Downloads') as td:
        root = Path(td)
        for name, expected in pins.items():
            raw = fetch(BASE + OLD_SOURCE + '/manager-updater/' + name, 1000000)
            if digest(raw) != expected:
                raise ValueError('old_source_changed_' + name)
            (root / name).write_bytes(raw)
        for name, expected in NEW_HASHES.items():
            raw = fetch(BASE + NEW_SOURCE + '/manager-updater/postcommit_v3/' + name,
                        1000000) if name != 'manager_postcommit_start_candidate.py' else fetch(
                        BASE + NEW_SOURCE + '/manager-updater/' + name, 1000000)
            if digest(raw) != expected:
                raise ValueError('new_source_changed_' + name)
            (root / name).write_bytes(raw)
        sys.path.insert(0, str(root))
        from manager_postcommit_start_candidate import prepare_launcher
        from manager_repair_release import (ARCHIVE, FILES, LAUNCHER, NATIVE_SOURCE,
            OLD_HELPER, SERVER, verify_release)
        from manager_helper_inventory import HELPER_FILES
        from manager_helper_release import verify_staged
        from manager_repair_rehearsal import rehearse_on_copy
        from build_manager_repair_app import build as build_finder
        from mac_sign_manager_capability import envelope
        from creative_transaction import safe_path
        from mac_offline_bootstrap_gate import verify_unchanged_app
        from strict_json import parse_signed_json
        resources = (home / 'Downloads/RapBrainManager_App_Beta14' /
                     'Rap Brain Manager Beta 14.app/Contents/Resources')
        launcher = resources / 'launch_manager.py'
        source = home / 'Downloads/rap-brain'
        state = home / 'Downloads/RapBrainManagerBackups/secure-update'
        if (digest(safe_path(launcher).read_bytes()) != LAUNCHER or
                digest(safe_path(resources / 'RapBrainManagerNative.swift').read_bytes()) != NATIVE_SOURCE or
                digest(safe_path(source / 'server.py').read_bytes()) != SERVER or
                digest(safe_path(resources / 'dashboard_beta14.html').read_bytes()) !=
                'd4c8c322c038125c19b19e3722ffd5a97e7974844cf31322a85660ab2a3e6b8b'):
            raise ValueError('active_baseline_changed')
        # The prior transactions are immutable evidence. Never discard or
        # overwrite their terminal journals to make a new repair possible.
        for journal in ('manager-repair.json', 'manager-transaction.json'):
            record = json.loads(safe_path(state / journal).read_bytes())
            if record.get('phase') != 'committed':
                raise ValueError('prior_transaction_not_committed')
        if any(os.path.lexists(state / name) for name in
               ('maintenance.ticket', 'bootstrap-intent.json',
                'maintenance-intent.json')):
            raise ValueError('maintenance_pending')
        if verify_unchanged_app(resources.parents[1], source, launcher) is not True:
            raise ValueError('active_app_signature_or_runtime_unknown')
        old_helper = verify_staged(state)
        old_helper_manifest = parse_signed_json(
            safe_path(old_helper / 'signed-manifest.json').read_bytes())['signed_payload']
        if (old_helper_manifest['sequence'] != 2 or
                old_helper_manifest['archive_sha256'] != OLD_HELPER):
            raise ValueError('active_helper_changed')
        with zipfile.ZipFile(io.BytesIO(archive_old)) as old:
            original_launcher = old.read('app/launch_manager.py')
            native = old.read('app/RapBrainManagerNative.swift')
            helper_zip = old.read('helper.zip')
        if digest(original_launcher) != LAUNCHER or digest(native) != NATIVE_SOURCE or digest(helper_zip) != OLD_HELPER:
            raise ValueError('prior_archive_mismatch')
        new_launcher = prepare_launcher(original_launcher)
        files = {'app/RapBrainManagerNative.swift': native,
                 'app/launch_manager.py': new_launcher, 'helper.zip': helper_zip}
        archive = packed(files)
        now = int(time.time())
        key = home / 'Library/Application Support/RapBrainManager/publisher_ed25519.key'
        validation = {'macos_copy_install': 'passed', 'rollback': 'passed',
                      'runtime': 'passed'}
        with zipfile.ZipFile(io.BytesIO(helper_zip)) as old_helper_zip:
            hashes = {name: digest(old_helper_zip.read('helper/' + name))
                      for name in HELPER_FILES}
        helper_signed = envelope({'schema': 'rapbrain-manager-helper-v1',
            'sequence': 3, 'issued_at': now - 1, 'expires_at': now + 14 * 86400,
            'production_install_authorized': True, 'validation': validation,
            'files': hashes, 'archive_sha256': digest(helper_zip),
            'archive_bytes': len(helper_zip)}, key)
        payload = {'schema': 'rapbrain-manager-repair-v1', 'sequence': 3,
            'issued_at': now - 1, 'expires_at': now + 14 * 86400,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': validation, 'baseline_launcher_sha256': LAUNCHER,
            'baseline_native_source_sha256': NATIVE_SOURCE,
            'baseline_helper_sha256': OLD_HELPER,
            'required_server_sha256': SERVER, 'archive_url': ARCHIVE,
            'archive_sha256': digest(archive), 'archive_bytes': len(archive),
            'files': {name: digest(files[name]) for name in FILES},
            'helper_manifest_base64': base64.b64encode(helper_signed).decode()}
        signed = envelope(payload, key)
        verify_release(signed, archive)
        report = rehearse_on_copy(source, launcher, state, signed, archive)
        if report != {'state': 'passed', 'active_files_modified': False,
                      'live_database_opened': False,
                      'live_configuration_opened': False}:
            raise ValueError('copy_rehearsal_failed')
        candidate = root / OUTPUT
        build_finder(candidate, release=signed, archive=archive, source=root)
        publication = packed({'manager-postcommit/manifest.json': signed,
                              'manager-postcommit/repair-3.zip': archive})
        if any(os.path.lexists(p) for p in (out, public)):
            raise ValueError('publication_destination_changed')
        fd = os.open(public, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(publication)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(candidate, out)
    return out, public


if __name__ == '__main__':
    try:
        app, publication = prepare(Path.home())
        print('REPARATION DU DEMARRAGE PREPAREE : OK')
        print('Application :', app)
        print('Publication :', publication)
        print('Aucun fichier actif modifié.')
    except Exception as exc:
        print('PREPARATION REFUSEE :', type(exc).__name__, '/',
              str(exc) if isinstance(exc, ValueError) else 'verification_failed',
              file=sys.stderr)
        raise SystemExit(2)
