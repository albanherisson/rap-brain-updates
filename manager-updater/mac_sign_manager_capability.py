#!/usr/bin/env python3
"""Sign the reviewed one-time capability using the owner's existing Mac key.

The private seed never leaves the Mac. Only exact pinned public code, a
manifest and signatures enter the resulting public ZIP. No app/data writes.
Run only after macOS copy installation and rollback checks have passed.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


CANDIDATE_COMMIT = '19d84a4db0713a658265df3358a68c1adc6388be'
CANDIDATE_SHA256 = '963ca5733de48d7d336b1c214a0b8f308aa582aa3484a5ae51769daafe0cf8a7'
CANDIDATE_URL = ('https://raw.githubusercontent.com/albanherisson/'
    'rap-brain-updates/' + CANDIDATE_COMMIT + '/manager-capability/capability-1.zip')
MANAGER_PIN = '5c7bda9ccdb4ee197ad10f907211f3b33ed74f5986066dd832bb3013df7dba78'
SERVER_SHA256 = 'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27'
LAUNCHER_SHA256 = '79130fbb4c0404c271c83242718945258e0f0dd8616cad61fb890228672dd2e4'
DASHBOARD_SHA256 = '43647e2449d4b7bfd6924502e728e8cf8bb5ebc0f7333d56d7e85bb0bbed1cb2'
ARCHIVE_URL = ('https://raw.githubusercontent.com/albanherisson/'
    'rap-brain-updates/main/manager-capability/capability-1.zip')
APP_FILES = ('launch_manager.py', 'dashboard_beta14.html',
    'beta14_launch_gate.py', 'beta14_owned_identity_candidate.py',
    'beta14_runtime_token_candidate.py', 'bootstrap_release.py',
    'manager_helper_inventory.py', 'manager_helper_release.py',
    'recovery_start_guards.py', 'server_graceful_shutdown_candidate.py',
    'server_lifetime_guard.py', 'server_worker_resume_candidate.py')
OUTPUT = 'RapBrain_Manager_Capability_Publication.zip'
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


def exact_file(path, limit=2_000_000):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('publisher_symlink_refused')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise ValueError('publisher_source_file_invalid')
    return path.read_bytes()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('publisher_redirect_refused')


def download_candidate():
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(CANDIDATE_URL,
            headers={'Accept-Encoding': 'identity'}), timeout=20) as response:
        if response.status != 200 or response.geturl() != CANDIDATE_URL:
            raise ValueError('publisher_candidate_url_changed')
        raw = response.read(2_000_001)
    if digest(raw) != CANDIDATE_SHA256 or len(raw) > 2_000_000:
        raise ValueError('publisher_candidate_hash_changed')
    return raw


def archive_files(archive):
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as outer:
            expected = sorted(['app/' + name for name in APP_FILES] + ['helper.zip'])
            if outer.namelist() != expected or len(set(expected)) != len(expected):
                raise ValueError('publisher_candidate_inventory')
            files = {name: outer.read(name) for name in expected}
        with zipfile.ZipFile(io.BytesIO(files['helper.zip'])) as inner:
            names = inner.namelist()
            if (len(names) != 41 or len(set(names)) != 41 or
                    any(not name.startswith('helper/') or
                        not name.endswith(('.py', '.swift')) for name in names)):
                raise ValueError('publisher_helper_inventory')
            hashes = {name.removeprefix('helper/'): digest(inner.read(name))
                      for name in names}
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError('publisher_candidate_archive_invalid') from exc
    return files, hashes


def sign(key_path, message):
    key_path = Path(key_path).absolute()
    seed = exact_file(key_path, 32)
    info = key_path.stat()
    if (len(seed) != 32 or info.st_uid != os.getuid() or
            info.st_mode & 0o077):
        raise ValueError('publisher_private_key_unsafe')
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    except ModuleNotFoundError:
        with tempfile.TemporaryDirectory(prefix='rapbrain-sign-message-') as temporary:
            path = Path(temporary) / 'message'
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
    if (len(public) != 32 or len(signature) != 64 or
            digest(public) != MANAGER_PIN):
        raise ValueError('publisher_manager_identity_mismatch')
    return public, signature


def envelope(payload, key_path):
    public, signature = sign(key_path, canonical(payload))
    return canonical({'signed_payload': payload,
        'signature_algorithm': 'Ed25519',
        'public_key_base64': base64.b64encode(public).decode(),
        'signature_base64': base64.b64encode(signature).decode()})


def public_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as package:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            package.writestr(info, files[name])
    return buffer.getvalue()


def prepare(home, archive, key_path, *, now=None):
    home = Path(home)
    now = int(time.time()) if now is None else now
    resources = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
        'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources')
    source = home / 'Downloads' / 'rap-brain'
    for path, expected in ((resources / 'launch_manager.py', LAUNCHER_SHA256),
                           (resources / 'dashboard_beta14.html', DASHBOARD_SHA256),
                           (source / 'server.py', SERVER_SHA256)):
        if digest(exact_file(path)) != expected:
            raise ValueError('publisher_active_baseline_changed')
    app = resources.parents[1]
    check = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                            str(app)], capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=90)
    if check.returncode:
        raise ValueError('publisher_active_app_signature_invalid')
    if digest(archive) != CANDIDATE_SHA256:
        raise ValueError('publisher_candidate_hash_changed')
    files, helper_hashes = archive_files(archive)
    validation = {'macos_copy_install': 'passed', 'rollback': 'passed',
                  'runtime': 'passed'}
    helper_payload = {'schema': 'rapbrain-manager-helper-v1',
        'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 14 * 86400,
        'production_install_authorized': True, 'validation': validation,
        'files': helper_hashes,
        'archive_sha256': digest(files['helper.zip']),
        'archive_bytes': len(files['helper.zip'])}
    helper_signed = envelope(helper_payload, key_path)
    payload = {'schema': 'rapbrain-manager-capability-v1',
        'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 14 * 86400,
        'production_install_authorized': True, 'validation': validation,
        'data_migrations': [],
        'baseline_launcher_sha256': LAUNCHER_SHA256,
        'baseline_dashboard_sha256': DASHBOARD_SHA256,
        'required_server_sha256': SERVER_SHA256,
        'archive_url': ARCHIVE_URL, 'archive_sha256': digest(archive),
        'archive_bytes': len(archive),
        'files': {name: digest(raw) for name, raw in files.items()},
        'helper_manifest_base64': base64.b64encode(helper_signed).decode()}
    signed = envelope(payload, key_path)
    return public_zip({'manager-capability/manifest.json': signed,
                       'manager-capability/capability-1.zip': archive})


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    home = Path.home()
    output = home / 'Downloads' / OUTPUT
    if output.exists() or output.is_symlink():
        raise ValueError('public_package_already_exists')
    key = home / 'Library' / 'Application Support' / 'RapBrainManager' / 'publisher_ed25519.key'
    package = prepare(home, download_candidate(), key)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(package)
        stream.flush()
        os.fsync(stream.fileno())
    print('PUBLICATION MANAGER PREPAREE : OK')
    print('Fichier public : ' + str(output))
    print('Clé privée absente du fichier public ; aucune installation effectuée.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('SIGNATURE REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
