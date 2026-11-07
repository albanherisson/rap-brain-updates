#!/usr/bin/env python3
"""Sign a one-time offline repair for macOS process-start date parsing.

The prior signed publications supply exact installed bytes. The private
publisher key stays on the owner Mac; only signed public payloads are exported.
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
SIGNED_REF = 'ec81423726d7fd53d85222e445d0df4b77cea702'
PREVIOUS_MANIFEST_HASH = '2d99fcdbfb76fedae86b858ad0006c44696bbc45b780a9508b79ff63fbddc2d4'
PREVIOUS_ARCHIVE_HASH = 'cb12ce263c943ad9fd1d5ac0d3f8d82517702f693292fb3a93755d9d57dbdd8d'
MANAGER_ARCHIVE_HASH = 'ab41245a9a93351effc55130a9b5655de9a2b72971e50fc8b9e09c59593db04d'
NEW_SOURCE = '15638ef4c6c93f266c208e6ed9d20049b14d7a36'
NEW_HASHES = {
    'app_bundle_backup.py': '54a557d0f90fd74e1d832be12e27a980ae754e2160c5e0e0c5eb3122aed23fd2',
    'manager_locale_repair_candidate.py': 'a3e2771286abd02fadecb926ff17e2a42aff32f55785743076fa630fcff85945',
    'manager_repair_release.py': '88741e10b978cb0f855ca4d77074a665b637cf717b4ee2ef4e8c33003e5841fc',
    'manager_repair_transaction.py': '1782b40ff4323bfa69da0719ce0aa77af791a28ae0a458f19483e735821148df',
    'manager_repair_rehearsal.py': '1b85052718ebb1291c2c3f122a645fcb9cf1d2553ea77faab9b344d64f71a8dd',
    'manager_repair_installer.py': 'e21ad27db6eece4c9bce3441fba19d766e3beee7b53d67c13197c70e75954f38',
    'build_manager_repair_app.py': 'cb3f2237d58557612996298c86c690e2543ed77f87490b49ceef53f405263379',
}
OUTPUT = 'Réparer la date du Manager.app'
PUBLIC = 'RapBrain_Manager_Locale_Publication.zip'


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
    signed_old = fetch(BASE + SIGNED_REF + '/manager-postcommit/manifest.json', 65536)
    archive_old = fetch(BASE + SIGNED_REF + '/manager-postcommit/repair-3.zip', 2000000)
    archive_manager = fetch(BASE + SIGNED_REF + '/manager-stable/update-3.zip', 2000000)
    if (digest(signed_old) != PREVIOUS_MANIFEST_HASH or
            digest(archive_old) != PREVIOUS_ARCHIVE_HASH or
            digest(archive_manager) != MANAGER_ARCHIVE_HASH):
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
            prefix = ('decoder-next/' if name == 'manager_locale_repair_candidate.py'
                      else 'manager-updater/locale_v4/')
            raw = fetch(BASE + NEW_SOURCE + '/' + prefix + name, 1000000)
            if digest(raw) != expected:
                raise ValueError('new_source_changed_' + name)
            (root / name).write_bytes(raw)
        sys.path.insert(0, str(root))
        from manager_locale_repair_candidate import launcher as prepare_launcher
        from manager_locale_repair_candidate import identity as prepare_identity
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
                '681026db23d1573c40d05cfb7cab73eb8cce0cf60ee03ec8983a6f04ea8e461f'):
            raise ValueError('active_baseline_changed')
        # The prior transactions are immutable evidence. Never discard or
        # overwrite their terminal journals to make a new repair possible.
        for journal in ('manager-repair.json', 'manager-postcommit-repair.json'):
            record = json.loads(safe_path(state / journal).read_bytes())
            if record.get('phase') != 'committed':
                raise ValueError('prior_transaction_not_committed')
        accepted = json.loads(safe_path(state / 'manager-accepted.json').read_bytes())
        if accepted != {'sequence': 3}:
            raise ValueError('manager_accepted_version_changed')
        if any(os.path.lexists(state / name) for name in
               ('maintenance.ticket', 'bootstrap-intent.json',
                'maintenance-intent.json')):
            raise ValueError('maintenance_pending')
        if verify_unchanged_app(resources.parents[1], source, launcher) is not True:
            raise ValueError('active_app_signature_or_runtime_unknown')
        old_helper = verify_staged(state)
        old_helper_manifest = parse_signed_json(
            safe_path(old_helper / 'signed-manifest.json').read_bytes())['signed_payload']
        if (old_helper_manifest['sequence'] != 3 or
                old_helper_manifest['archive_sha256'] != OLD_HELPER):
            raise ValueError('active_helper_changed')
        with zipfile.ZipFile(io.BytesIO(archive_old)) as old:
            native = old.read('app/RapBrainManagerNative.swift')
            helper_zip = old.read('helper.zip')
        with zipfile.ZipFile(io.BytesIO(archive_manager)) as manager_zip:
            original_launcher = manager_zip.read('app/launch_manager.py')
        if (digest(original_launcher) != LAUNCHER or digest(native) != NATIVE_SOURCE
                or digest(helper_zip) != OLD_HELPER):
            raise ValueError('prior_archive_mismatch')
        new_launcher = prepare_launcher(original_launcher)
        with zipfile.ZipFile(io.BytesIO(helper_zip)) as old_helper_zip:
            old_members = {name: old_helper_zip.read('helper/' + name)
                           for name in HELPER_FILES}
        new_members = dict(old_members)
        new_members['process_start_identity.py'] = prepare_identity(
            old_members['process_start_identity.py'])
        # The live app has Finder's root Icon\r entry. Both the installer and
        # the staged helper must accept exactly that backed-up root entry.
        if digest(old_members['app_bundle_backup.py']) != pins['app_bundle_backup.py']:
            raise ValueError('old_app_backup_changed')
        new_members['app_bundle_backup.py'] = (root / 'app_bundle_backup.py').read_bytes()
        helper_zip = packed({'helper/' + name: new_members[name]
                             for name in HELPER_FILES})
        files = {'app/RapBrainManagerNative.swift': native,
                 'app/launch_manager.py': new_launcher, 'helper.zip': helper_zip}
        archive = packed(files)
        now = int(time.time())
        key = home / 'Library/Application Support/RapBrainManager/publisher_ed25519.key'
        validation = {'macos_copy_install': 'passed', 'rollback': 'passed',
                      'runtime': 'passed'}
        hashes = {name: digest(new_members[name]) for name in HELPER_FILES}
        helper_signed = envelope({'schema': 'rapbrain-manager-helper-v1',
            'sequence': 4, 'issued_at': now - 1, 'expires_at': now + 14 * 86400,
            'production_install_authorized': True, 'validation': validation,
            'files': hashes, 'archive_sha256': digest(helper_zip),
            'archive_bytes': len(helper_zip)}, key)
        payload = {'schema': 'rapbrain-manager-repair-v1', 'sequence': 4,
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
        publication = packed({'manager-locale/manifest.json': signed,
                              'manager-locale/repair-4.zip': archive})
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
