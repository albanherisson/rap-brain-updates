#!/usr/bin/env python3
"""Sign one reviewed Manager update with the existing private Mac key.

Creates only a public ZIP in Downloads. The key never enters the archive or
GitHub. Does not stop processes, install code, open SQLite, or read Ollama.
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


CANDIDATE_COMMIT = '5a884fd1540939472caf115116197561350bf322'
CANDIDATE_URL = ('https://raw.githubusercontent.com/albanherisson/'
    'rap-brain-updates/' + CANDIDATE_COMMIT + '/manager-stable/update-1.zip')
ARCHIVE_URL = ('https://raw.githubusercontent.com/albanherisson/'
    'rap-brain-updates/main/manager-stable/update-1.zip')
ARCHIVE_SHA256 = 'eee67d2a0902fc308dadefa33cdc3deea294ce2862e0ee61b09856d1868b9cf1'
PAYLOAD_SHA256 = '1e2f02a9e85187bca5464526388adb701790c23918f1e5d92bd63889a11db764'
LAUNCHER_SHA256 = 'e072f29f2416ed286c67f8faa73f517a1fb5deafb20cf125ac8f8417722a6464'
DASHBOARD_SHA256 = 'b1b57c4036f658cad83fc7642a2476e3582f2f8bd73ae671ceb36d2f7020713f'
SERVER_SHA256 = 'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27'
CREATIVE_SHA256 = 'b770bdf034caa600f75497325f80759d4f372258fa0e911e28f29d214abe85f3'
MANAGER_PIN = '5c7bda9ccdb4ee197ad10f907211f3b33ed74f5986066dd832bb3013df7dba78'
OUTPUT = 'RapBrain_Manager_Version_Publication.zip'
MEMBER = 'app/launch_manager.py'
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
        raise ValueError('publisher_source_invalid')
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
        raw = response.read(250_001)
    if not 0 < len(raw) <= 250_000 or digest(raw) != ARCHIVE_SHA256:
        raise ValueError('publisher_candidate_changed')
    return raw


def check_archive(archive):
    if type(archive) is not bytes or digest(archive) != ARCHIVE_SHA256:
        raise ValueError('publisher_candidate_changed')
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            if zipped.namelist() != [MEMBER]:
                raise ValueError('publisher_inventory_changed')
            item = zipped.getinfo(MEMBER)
            if (item.flag_bits & 1 or item.is_dir() or
                    item.compress_type != zipfile.ZIP_DEFLATED or
                    stat.S_IFMT(item.external_attr >> 16) != stat.S_IFREG):
                raise ValueError('publisher_inventory_changed')
            payload = zipped.read(item)
    except (zipfile.BadZipFile, RuntimeError, EOFError) as exc:
        raise ValueError('publisher_archive_invalid') from exc
    if digest(payload) != PAYLOAD_SHA256:
        raise ValueError('publisher_payload_changed')
    compile(payload, MEMBER, 'exec')
    return payload


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


def app_inventory(app):
    output = {}
    for path in sorted(app.rglob('*')):
        if path.is_symlink():
            raise ValueError('publisher_copy_symlink_refused')
        if path.is_file():
            item = path.stat()
            if not stat.S_ISREG(item.st_mode):
                raise ValueError('publisher_copy_special_file')
            output[str(path.relative_to(app))] = (digest(path.read_bytes()),
                stat.S_IMODE(item.st_mode))
        elif not path.is_dir():
            raise ValueError('publisher_copy_special_file')
    return output


def rehearse_on_copy(app, payload, backup_root, *, runner=subprocess.run):
    """Exercise Mac signing and exact restoration entirely in private copies."""
    backup_root = Path(backup_root)
    if not backup_root.is_dir() or backup_root.is_symlink():
        raise ValueError('publisher_backup_root_missing')
    original_inventory = app_inventory(app)
    if not original_inventory:
        raise ValueError('publisher_original_app_empty')
    with tempfile.TemporaryDirectory(prefix='manager-version-copy-', dir=backup_root) as temp:
        root = Path(temp)
        original = root / 'original.app'
        candidate = root / 'candidate.app'
        restored = root / 'restored.app'
        for destination in (original, candidate):
            result = runner(['/usr/bin/ditto', str(app), str(destination)],
                            capture_output=True, stdin=subprocess.DEVNULL,
                            timeout=90)
            if result.returncode or app_inventory(destination) != original_inventory:
                raise ValueError('publisher_app_copy_changed')
            result = runner(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                             str(destination)], capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=90)
            if result.returncode:
                raise ValueError('publisher_original_copy_signature_invalid')
        launcher = candidate / 'Contents' / 'Resources' / 'launch_manager.py'
        if digest(exact_file(launcher)) != LAUNCHER_SHA256:
            raise ValueError('publisher_copy_baseline_changed')
        launcher.write_bytes(payload)
        result = runner(['/usr/bin/codesign', '--force', '--deep', '--sign', '-',
                         str(candidate)], capture_output=True,
                        stdin=subprocess.DEVNULL, timeout=90)
        if result.returncode:
            raise ValueError('publisher_candidate_copy_sign_failed')
        result = runner(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                         str(candidate)], capture_output=True,
                        stdin=subprocess.DEVNULL, timeout=90)
        if result.returncode or digest(launcher.read_bytes()) != PAYLOAD_SHA256:
            raise ValueError('publisher_candidate_copy_verify_failed')
        result = runner(['/usr/bin/ditto', str(original), str(restored)],
                        capture_output=True, stdin=subprocess.DEVNULL, timeout=90)
        if result.returncode or app_inventory(restored) != original_inventory:
            raise ValueError('publisher_copy_rollback_changed')
        result = runner(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                         str(restored)], capture_output=True,
                        stdin=subprocess.DEVNULL, timeout=90)
        if result.returncode or app_inventory(app) != original_inventory:
            raise ValueError('publisher_copy_rollback_signature_invalid')
    return True


def prepare(home, archive, key_path, *, now=None, rehearsal=rehearse_on_copy):
    home = Path(home)
    now = int(time.time()) if now is None else now
    resources = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
        'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources')
    source = home / 'Downloads' / 'rap-brain'
    for path, expected in ((resources / 'launch_manager.py', LAUNCHER_SHA256),
                           (resources / 'dashboard_beta14.html', DASHBOARD_SHA256),
                           (source / 'server.py', SERVER_SHA256),
                           (source / 'creative_engine.py', CREATIVE_SHA256)):
        if digest(exact_file(path)) != expected:
            raise ValueError('publisher_active_baseline_changed')
    app = resources.parents[1]
    result = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                             str(app)], capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=90)
    if result.returncode:
        raise ValueError('publisher_active_app_signature_invalid')
    payload = check_archive(archive)
    if rehearsal(app, payload, home / 'Downloads' / 'RapBrainManagerBackups') is not True:
        raise ValueError('publisher_copy_rehearsal_failed')
    signed = {'schema': 'rapbrain-manager-production-v1',
        'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 14 * 86400,
        'production_install_authorized': True, 'data_migrations': [],
        'validation': {'macos_copy_install': 'passed',
                       'rollback': 'passed', 'runtime': 'passed'},
        'files': [{'path': MEMBER, 'baseline_sha256': LAUNCHER_SHA256,
                   'payload_sha256': digest(payload)}],
        'required_server_sha256': SERVER_SHA256,
        'archive_url': ARCHIVE_URL, 'archive_sha256': digest(archive),
        'archive_bytes': len(archive)}
    public, signature = sign(key_path, canonical(signed))
    envelope = canonical({'signed_payload': signed,
        'signature_algorithm': 'Ed25519',
        'public_key_base64': base64.b64encode(public).decode(),
        'signature_base64': base64.b64encode(signature).decode()})
    return public_zip({'manager-stable/manifest.json': envelope,
                       'manager-stable/update-1.zip': archive})


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
    print('MISE A JOUR MANAGER SIGNEE : OK')
    print('Fichier public : ' + str(output))
    print('Aucune installation effectuee. Cle privee absente du ZIP public.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('SIGNATURE REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
