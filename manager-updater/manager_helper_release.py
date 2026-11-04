"""Verify a Manager-signed external helper candidate before any extraction.

No production publication exists. This verifier is independent of the
general server/app release and does not authorize replacing any active file.
"""
import base64
import fcntl
import io
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import time
import zipfile

from bootstrap_release import PUBLISHER_PIN
from creative_release import Refused, canonical, digest
from creative_transaction import fsync_dir
from ed25519_runtime import verify_signature
from manager_helper_bundle import HELPER_FILES
from strict_json import parse_signed_json
from worker_activity_gate import _state


HEX = re.compile(r'[0-9a-f]{64}\Z')
MAX_ARCHIVE = 1_000_000


def verify_manifest(raw, *, pinned_key=PUBLISHER_PIN, now=None):
    if type(raw) is not bytes or not 0 < len(raw) <= 65536:
        raise Refused('manager_helper_manifest_size')
    envelope = parse_signed_json(raw)
    if (type(envelope) is not dict or envelope.keys() !=
            {'signed_payload', 'signature_algorithm', 'signature_base64',
             'public_key_base64'} or envelope['signature_algorithm'] != 'Ed25519'):
        raise Refused('manager_helper_envelope')
    try:
        public = base64.b64decode(envelope['public_key_base64'], validate=True)
        signature = base64.b64decode(envelope['signature_base64'], validate=True)
        if (len(public) != 32 or len(signature) != 64 or
                digest(public) != pinned_key):
            raise Refused('manager_helper_publisher_mismatch')
        signed = envelope['signed_payload']
        verify_signature(public, signature, canonical(signed))
    except Refused:
        raise
    except (TypeError, ValueError) as exc:
        raise Refused('manager_helper_signature_invalid') from exc
    current = int(time.time()) if now is None else now
    if (type(signed) is not dict or signed.keys() !=
            {'schema', 'sequence', 'issued_at', 'expires_at',
             'production_install_authorized', 'validation', 'files',
             'archive_sha256', 'archive_bytes'} or
            signed['schema'] != 'rapbrain-manager-helper-v1' or
            signed['production_install_authorized'] is not True or
            signed['validation'] != {'macos_copy_install': 'passed',
                                     'rollback': 'passed', 'runtime': 'passed'} or
            type(signed['sequence']) is not int or signed['sequence'] < 1 or
            type(signed['issued_at']) is not int or
            type(signed['expires_at']) is not int or
            not 0 <= signed['issued_at'] <= current < signed['expires_at'] <=
                signed['issued_at'] + 31 * 86400 or
            type(signed['archive_sha256']) is not str or
            not HEX.fullmatch(signed['archive_sha256']) or
            type(signed['archive_bytes']) is not int or
            not 0 < signed['archive_bytes'] <= MAX_ARCHIVE or
            type(signed['files']) is not dict or
            signed['files'].keys() != set(HELPER_FILES) or
            any(type(value) is not str or not HEX.fullmatch(value)
                for value in signed['files'].values())):
        raise Refused('manager_helper_release_scope')
    return signed


def verify_archive(raw, manifest):
    if (type(raw) is not bytes or type(manifest) is not dict or
            len(raw) != manifest['archive_bytes'] or
            digest(raw) != manifest['archive_sha256']):
        raise Refused('manager_helper_archive_integrity')
    output = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if ([member.filename for member in members] !=
                    ['helper/' + name for name in HELPER_FILES] or
                    any(member.flag_bits & 1 or member.is_dir() or
                        member.compress_type != zipfile.ZIP_DEFLATED or
                        not 0 < member.file_size <= 250_000 or
                        stat.S_IFMT(member.external_attr >> 16) != stat.S_IFREG
                        for member in members) or
                    sum(member.file_size for member in members) > MAX_ARCHIVE):
                raise Refused('manager_helper_archive_layout')
            for item, name in zip(members, HELPER_FILES):
                raw_file = archive.read(item)
                if digest(raw_file) != manifest['files'][name]:
                    raise Refused('manager_helper_member_changed')
                if name.endswith('.py'):
                    compile(raw_file, name, 'exec')
                elif (b'import CryptoKit' not in raw_file or
                      b'isValidSignature(signature, for: message)' not in raw_file):
                    raise Refused('manager_helper_verifier_changed')
                output[name] = raw_file
    except (zipfile.BadZipFile, EOFError, RuntimeError, SyntaxError,
            UnicodeError) as exc:
        raise Refused('manager_helper_archive_invalid') from exc
    return output


def stage_verified(state, signed_manifest, archive, *, pinned_key=PUBLISHER_PIN,
                   now=None):
    """Create one private helper directory from authenticated bytes only.

    The caller still needs a separate signed, reviewed transaction to update
    the Manager app. Staging alone grants no install permission.
    """
    manifest = verify_manifest(signed_manifest, pinned_key=pinned_key, now=now)
    members = verify_archive(archive, manifest)
    state = _state(state)
    lock = os.open(state / 'helper-stage.lock',
                   os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077):
            raise Refused('manager_helper_lock_unsafe')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refused('manager_helper_stage_busy') from exc
        if any(os.path.lexists(state / name) for name in
               ('helper', 'bootstrap-intent.json', 'maintenance.ticket',
                'maintenance-intent.json')):
            raise Refused('manager_helper_existing_or_maintenance')
        temporary = state / ('helper-tmp-' + secrets.token_hex(16))
        temporary.mkdir(mode=0o700)
        try:
            manifest_path = temporary / 'signed-manifest.json'
            fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(signed_manifest)
                stream.flush()
                os.fsync(stream.fileno())
            for name in HELPER_FILES:
                path = temporary / name
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(members[name])
                    stream.flush()
                    os.fsync(stream.fileno())
            fsync_dir(temporary)
            if os.path.lexists(state / 'helper'):
                raise Refused('manager_helper_race')
            os.rename(temporary, state / 'helper')
            fsync_dir(state)
        except BaseException:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
    finally:
        os.close(lock)
    return {'staged': True, 'files': len(HELPER_FILES),
            'archive_sha256': manifest['archive_sha256']}


def verify_staged(state, *, pinned_key=PUBLISHER_PIN, now=None):
    """Authenticate the exact private helper again before importing its code."""
    state = _state(state)
    folder = state / 'helper'
    if folder.is_symlink() or not folder.is_dir():
        raise Refused('manager_helper_not_staged')
    info = folder.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Refused('manager_helper_directory_unsafe')
    if set(os.listdir(folder)) != set(HELPER_FILES) | {'signed-manifest.json'}:
        raise Refused('manager_helper_staged_layout')
    path = folder / 'signed-manifest.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise Refused('manager_helper_staged_manifest')
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise Refused('manager_helper_manifest_unsafe')
    raw = path.read_bytes()
    # The expiry limits new staging, not the lifetime of already installed
    # helper code. Recheck its signature and signed hashes at issuance time.
    try:
        issued = parse_signed_json(raw)['signed_payload']['issued_at']
    except (KeyError, TypeError, ValueError) as exc:
        raise Refused('manager_helper_staged_manifest') from exc
    manifest = verify_manifest(raw, pinned_key=pinned_key,
                               now=issued if now is None else now)
    for name in HELPER_FILES:
        path = folder / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 250_000:
            raise Refused('manager_helper_staged_file_unsafe')
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or \
                digest(path.read_bytes()) != manifest['files'][name]:
            raise Refused('manager_helper_staged_file_changed')
    return folder
