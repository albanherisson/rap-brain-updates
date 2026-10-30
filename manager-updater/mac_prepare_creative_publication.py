#!/usr/bin/env python3
"""Prepare public signed rotation and P8 release on the publisher's Mac.

The Manager key authorizes only the Creative trust change; a separate new
Creative key signs the engine release. Neither private key enters the ZIP.
No installed code, database, Ollama setting, or process is modified.
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
import zipfile

from creative_release import verify_archive, verify_manifest
from creative_trust_rotation import PUBLISHER_PIN, candidate_for_key, verify_rotation
from mac_publish_creative_p8 import (BASELINE, SERVER, canonical,
    fetch_pinned_gate, one_file_archive, production_payload, sha, sign_with_key)


SWIFT_GENERATE = '''import Foundation
import CryptoKit
let key = Curve25519.Signing.PrivateKey()
FileHandle.standardOutput.write(key.rawRepresentation)
'''
MANAGER_PUBLIC = base64.b64decode('LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY=')
NAME = 'RapBrain_Creative_Publication.zip'


def private_parent(path):
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError('publisher_key_symlink')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('publisher_key_directory_unsafe')


def private_bytes(path):
    if path.is_symlink():
        raise ValueError('publisher_key_symlink')
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            info.st_mode & 0o077 or info.st_size != 32):
        raise ValueError('publisher_key_unsafe')
    return path.read_bytes()


def create_private(path, raw):
    if type(raw) is not bytes or len(raw) != 32:
        raise ValueError('publisher_seed_invalid')
    private_parent(path.parent)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def new_seed():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ModuleNotFoundError:
        result = subprocess.run(['/usr/bin/swift', '-e', SWIFT_GENERATE],
                                capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
        if result.returncode or result.stderr or len(result.stdout) != 32:
            raise ValueError('creative_key_generation_failed')
        return result.stdout
    return Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())


def ensure_creative_key(home):
    support = home / 'Library' / 'Application Support' / 'RapBrainCreativePublisher'
    backup = home / 'Downloads' / 'RapBrainManagerBackups' / 'publisher-keys'
    key = support / 'creative_ed25519.key'
    copy = backup / 'creative_ed25519.key'
    private_parent(support)
    private_parent(backup)
    existing = [private_bytes(path) for path in (key, copy) if path.exists()]
    if existing and any(raw != existing[0] for raw in existing):
        raise ValueError('creative_key_backup_mismatch')
    raw = existing[0] if existing else new_seed()
    if not key.exists():
        create_private(key, raw)
    if not copy.exists():
        create_private(copy, raw)
    if private_bytes(key) != private_bytes(copy):
        raise ValueError('creative_key_backup_mismatch')
    return key


def envelope(payload, public, signature):
    if type(public) is not bytes or len(public) != 32 or len(signature) != 64:
        raise ValueError('publisher_signature_invalid')
    return canonical({'signed_payload': payload, 'signature_algorithm': 'Ed25519',
        'public_key_base64': base64.b64encode(public).decode('ascii'),
        'signature_base64': base64.b64encode(signature).decode('ascii')})


def rotation_payload(original, public, now):
    candidate = candidate_for_key(original, public)
    return {'schema': 'rapbrain-creative-trust-rotation-v1', 'sequence': 1,
            'issued_at': now - 1, 'expires_at': now + 14 * 86400,
            'production_install_authorized': True,
            'target': 'creative_release.py', 'data_migrations': [],
            'baseline_sha256': sha(original), 'candidate_sha256': sha(candidate),
            'new_public_key_base64': base64.b64encode(public).decode('ascii'),
            'new_public_key_sha256': sha(public)}


def public_zip(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as package:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            package.writestr(info, files[name])
    return output.getvalue()


def prepare(home, temporary, *, now=None, manager_key=None, creative_key=None,
            candidate_code=None):
    home = Path(home)
    now = int(time.time()) if now is None else now
    if sys.platform != 'darwin' or sha(MANAGER_PUBLIC) != PUBLISHER_PIN:
        raise ValueError('mac_publisher_identity_required')
    folder = Path(temporary)
    source = home / 'Downloads' / 'rap-brain'
    original = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
                'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources' /
                'creative_release.py').read_bytes()
    if candidate_code is None:
        gate = fetch_pinned_gate(folder)
        candidate_code = gate.signed_candidate(folder)
        gate.pinned_file(source / 'creative_engine.py', BASELINE)
        gate.pinned_file(source / 'server.py', SERVER)
    archive = one_file_archive(candidate_code)
    manager_key = (home / 'Library' / 'Application Support' / 'RapBrainManager' /
                   'publisher_ed25519.key') if manager_key is None else Path(manager_key)
    creative_key = ensure_creative_key(home) if creative_key is None else Path(creative_key)
    release_key = sign_with_key(creative_key, b'rapbrain-public-key-check', folder)
    if release_key is None or sha(release_key[0]) in (PUBLISHER_PIN,
            'ae32610121418b50adcc8726df567a22ed7b3af67f804ef9aaaa7a1a4efce504'):
        raise ValueError('creative_key_invalid_or_reused')
    creative_public = release_key[0]
    trust_payload = rotation_payload(original, creative_public, now)
    manager_signature = sign_with_key(manager_key, canonical(trust_payload), folder)
    if manager_signature is None or manager_signature[0] != MANAGER_PUBLIC:
        raise ValueError('manager_publisher_key_mismatch')
    trust = envelope(trust_payload, MANAGER_PUBLIC, manager_signature[1])
    verify_rotation(trust, original, now=now)
    engine_payload = production_payload(archive, now=now)
    signed_engine = sign_with_key(creative_key, canonical(engine_payload), folder)
    if signed_engine is None or signed_engine[0] != creative_public:
        raise ValueError('creative_publisher_key_changed')
    release = envelope(engine_payload, creative_public, signed_engine[1])
    verified = verify_manifest(release, now=now, pinned_key=sha(creative_public))
    verify_archive(archive, verified)
    return public_zip({'manager-trust/creative-rotation-1.json': trust,
                       'creative-stable/manifest.json': release,
                       'creative-stable/engine-1.zip': archive}), sha(creative_public)


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    home = Path.home()
    output = home / 'Downloads' / NAME
    if output.exists() or output.is_symlink():
        raise ValueError('public_package_already_exists')
    with tempfile.TemporaryDirectory(prefix='rapbrain-publication-') as temporary:
        raw, pin = prepare(home, temporary)
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print('PUBLICATION PREPAREE : OK')
    print('Fichier public : ' + str(output))
    print('Empreinte de la nouvelle clé Creative : ' + pin)
    print('Clés privées absentes du fichier public ; aucune installation effectuée.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('PUBLICATION REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
