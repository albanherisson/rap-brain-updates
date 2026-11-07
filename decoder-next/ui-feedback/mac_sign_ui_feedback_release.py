#!/usr/bin/env python3
"""Rehearse a server-only Manager update on Mac copies, then sign a public ZIP.

The active server, app, SQLite database, library and Ollama configuration are
never written. The private publisher key is read locally and never packaged.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


COMMIT = 'b9c8b6ff0f29764df29bf852c81350673004942c'
CANDIDATE_URL = ('https://raw.githubusercontent.com/albanherisson/'
                 'rap-brain-updates/' + COMMIT + '/decoder-next/ui-feedback/server-release.py')
CANDIDATE_SHA256 = '9223d347148f2ab79f96cda800572439eda20b7b21da89e35b683aaf001810b9'
UI_BASE_SHA256 = '3fdd85c514dbd5d0625b1c592682d9299c6c8394c30330b128d0462d841327c8'
BASELINE_SHA256 = 'b4d9f120ee5f2e1fedf4c1f73794bd4d3c3f4044bbd686d748b7cd3b94b89233'
PUBLISHER_PIN = '5c7bda9ccdb4ee197ad10f907211f3b33ed74f5986066dd832bb3013df7dba78'
ARCHIVE_URL = ('https://raw.githubusercontent.com/albanherisson/'
               'rap-brain-updates/main/manager-stable/update-5.zip')
OUTPUT = 'RapBrain_UI_Feedback_Publication.zip'
SWIFT_SIGN = '''import Foundation
import CryptoKit
let args = CommandLine.arguments
guard args.count == 3,
 let seed = try? Data(contentsOf: URL(fileURLWithPath: args[1])),
 let message = try? Data(contentsOf: URL(fileURLWithPath: args[2])),
 seed.count == 32,
 let key = try? Curve25519.Signing.PrivateKey(rawRepresentation: seed) else { exit(2) }
print(key.publicKey.rawRepresentation.base64EncodedString())
print(try key.signature(for: message).base64EncodedString())
'''


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode()


def regular_file(path, limit=2_000_000):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('source_symlink_refused')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise ValueError('source_file_invalid')
    return path.read_bytes()


def safe_dir(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_dir():
        raise ValueError('backup_directory_invalid')
    return path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('candidate_redirect_refused')


def download_candidate():
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(CANDIDATE_URL,
            headers={'Accept-Encoding': 'identity'}), timeout=20) as response:
        if response.status != 200 or response.geturl() != CANDIDATE_URL:
            raise ValueError('candidate_response_invalid')
        raw = response.read(120_001)
    if not 0 < len(raw) <= 120_000 or digest(raw) != CANDIDATE_SHA256:
        raise ValueError('candidate_hash_mismatch')
    compile(raw, 'server.py', 'exec')
    return raw


def zip_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, files[name])
    return stream.getvalue()


def app_inventory(app):
    entries = {}
    for path in sorted(app.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('app_special_file_refused')
        if path.is_file():
            item = path.stat()
            if not stat.S_ISREG(item.st_mode):
                raise ValueError('app_special_file_refused')
            entries[str(path.relative_to(app))] = (digest(path.read_bytes()),
                                                   stat.S_IMODE(item.st_mode))
    if not entries:
        raise ValueError('app_empty')
    return entries


def verify_app(app, runner=subprocess.run):
    result = runner(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=90)
    if result.returncode:
        raise ValueError('app_signature_invalid')


def rehearse_on_mac_copies(source, app, backup_root, original, candidate,
                           runner=subprocess.run):
    """Use only disposable server/app copies, with an exact restoration check."""
    backup_root = safe_dir(backup_root)
    app = safe_dir(app)
    if digest(regular_file(source)) != digest(original):
        raise ValueError('active_server_changed')
    static_ui = source.parent / 'static/app.js'
    original_ui = regular_file(static_ui)
    if digest(original_ui) != UI_BASE_SHA256:
        raise ValueError('active_ui_baseline_changed')
    before = app_inventory(app)
    verify_app(app, runner)
    with tempfile.TemporaryDirectory(prefix='decoder-release-copy-', dir=backup_root) as temp:
        root = Path(temp)
        app_copy = root / 'Manager.app'
        result = runner(['/usr/bin/ditto', str(app), str(app_copy)],
                        capture_output=True, stdin=subprocess.DEVNULL, timeout=90)
        if result.returncode or app_inventory(app_copy) != before:
            raise ValueError('app_copy_mismatch')
        verify_app(app_copy, runner)
        ui_copy = root / 'app-original.js'
        shutil.copy2(static_ui, ui_copy)
        if ui_copy.read_bytes() != original_ui:
            raise ValueError('ui_copy_mismatch')
        original_copy = root / 'server-original.py'
        trial_copy = root / 'server-trial.py'
        shutil.copy2(source, original_copy)
        shutil.copy2(source, trial_copy)
        if original_copy.read_bytes() != original or trial_copy.read_bytes() != original:
            raise ValueError('server_copy_mismatch')
        trial_copy.write_bytes(candidate)
        if digest(trial_copy.read_bytes()) != CANDIDATE_SHA256:
            raise ValueError('server_trial_mismatch')
        compile(trial_copy.read_bytes(), str(trial_copy), 'exec')
        shutil.copy2(original_copy, trial_copy)
        if trial_copy.read_bytes() != original:
            raise ValueError('server_copy_rollback_mismatch')
        if ui_copy.read_bytes() != original_ui:
            raise ValueError('ui_copy_changed')
        if app_inventory(app_copy) != before:
            raise ValueError('app_copy_changed')
    if (digest(regular_file(source)) != digest(original) or
            regular_file(static_ui) != original_ui or app_inventory(app) != before):
        raise ValueError('active_code_changed')
    return True


def sign(key_path, message):
    key_path = Path(key_path).absolute()
    seed = regular_file(key_path, 32)
    info = key_path.stat()
    if len(seed) != 32 or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('publisher_private_key_unsafe')
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    except ModuleNotFoundError:
        with tempfile.TemporaryDirectory(prefix='rapbrain-sign-message-') as temp:
            path = Path(temp) / 'message'
            path.write_bytes(message)
            path.chmod(0o600)
            result = subprocess.run(['/usr/bin/swift', '-e', SWIFT_SIGN,
                str(key_path), str(path)], capture_output=True,
                stdin=subprocess.DEVNULL, timeout=120)
        if result.returncode or result.stderr:
            raise ValueError('publisher_swift_signature_failed')
        parts = result.stdout.splitlines()
        if len(parts) != 2:
            raise ValueError('publisher_swift_signature_invalid')
        try:
            public, signature = (base64.b64decode(part, validate=True)
                                 for part in parts)
        except ValueError as exc:
            raise ValueError('publisher_swift_signature_invalid') from exc
    else:
        key = Ed25519PrivateKey.from_private_bytes(seed)
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        signature = key.sign(message)
    if len(public) != 32 or len(signature) != 64 or digest(public) != PUBLISHER_PIN:
        raise ValueError('publisher_identity_mismatch')
    return public, signature


def prepare(home, candidate, *, signer=sign, rehearsal=rehearse_on_mac_copies,
            now=None):
    home = Path(home)
    source = home / 'Downloads/rap-brain/server.py'
    app = (home / 'Downloads/RapBrainManager_App_Beta14' /
           'Rap Brain Manager Beta 14.app')
    state = home / 'Downloads/RapBrainManagerBackups/secure-update'
    receipt = json.loads(regular_file(state / 'manager-accepted.json', 256))
    if type(receipt) is not dict or receipt != {'sequence': 4}:
        raise ValueError('manager_sequence_not_four')
    if (state / 'maintenance.ticket').exists() or (state / 'maintenance.ticket').is_symlink():
        raise ValueError('maintenance_in_progress')
    original = regular_file(source)
    if digest(regular_file(home / 'Downloads/rap-brain/static/app.js')) != UI_BASE_SHA256:
        raise ValueError('active_ui_baseline_changed')
    if digest(original) != BASELINE_SHA256 or digest(candidate) != CANDIDATE_SHA256:
        raise ValueError('code_baseline_mismatch')
    backup_root = home / 'Downloads/RapBrainManagerBackups'
    if rehearsal(source, app, backup_root, original, candidate) is not True:
        raise ValueError('copy_rehearsal_failed')
    archive = zip_bytes({'server.py': candidate})
    issued = int(time.time()) if now is None else now
    signed = {'schema':'rapbrain-manager-production-v1',
        'sequence':5, 'issued_at':issued-1, 'expires_at':issued+14*86400,
        'production_install_authorized':True, 'data_migrations':[],
        'validation':{'macos_copy_install':'passed','rollback':'passed','runtime':'passed'},
        'files':[{'path':'server.py','baseline_sha256':BASELINE_SHA256,
                  'payload_sha256':CANDIDATE_SHA256}],
        'required_server_sha256':BASELINE_SHA256,
        'archive_url':ARCHIVE_URL,'archive_sha256':digest(archive),
        'archive_bytes':len(archive)}
    public, signature = signer(home / 'Library/Application Support/RapBrainManager/publisher_ed25519.key',
                               canonical(signed))
    envelope = canonical({'signed_payload':signed,'signature_algorithm':'Ed25519',
        'public_key_base64':base64.b64encode(public).decode(),
        'signature_base64':base64.b64encode(signature).decode()})
    return zip_bytes({'manager-stable/manifest.json':envelope,
                      'manager-stable/update-5.zip':archive})


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    home = Path.home()
    output = home / 'Downloads' / OUTPUT
    if output.exists() or output.is_symlink():
        raise ValueError('public_package_already_exists')
    package = prepare(home, download_candidate())
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(package)
        stream.flush()
        os.fsync(stream.fileno())
    print('PUBLICATION INTERFACE PREPAREE : OK')
    print('Fichier public : ' + str(output))
    print('Copies Mac, signature et retour arrière vérifiés ; aucune installation effectuée.')
    print('Clé privée absente du ZIP public.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('PUBLICATION REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
