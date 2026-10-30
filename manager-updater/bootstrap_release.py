"""Verify a two-file, locally signed guarded bootstrap before any live swap.

The publisher private key must remain on the owner's Mac. A signed bootstrap
has not been created. Verification alone never installs or launches anything.
"""
import base64
import hashlib
import io
import re
import stat
import time
import zipfile

from creative_release import Refused, canonical, digest
from ed25519_runtime import verify_signature
from recovery_start_guards import prepare_launcher, prepare_server
from strict_json import parse_signed_json


PUBLISHER_PIN = '5c7bda9ccdb4ee197ad10f907211f3b33ed74f5986066dd832bb3013df7dba78'
HEX = re.compile(r'[0-9a-f]{64}\Z')
FILES = ('server.py', 'launch_manager.py')


def verify_bootstrap(manifest_bytes, archive_bytes, original_server,
                     original_launcher, *, pinned_key=PUBLISHER_PIN, now=None):
    """Return authenticated candidate bytes; no filesystem or process access."""
    if type(manifest_bytes) is not bytes or len(manifest_bytes) > 65536:
        raise Refused('bootstrap_manifest_size')
    envelope = parse_signed_json(manifest_bytes)
    if type(envelope) is not dict or envelope.keys() != {
            'signed_payload', 'signature_algorithm', 'signature_base64', 'public_key_base64'}:
        raise Refused('bootstrap_envelope')
    if envelope['signature_algorithm'] != 'Ed25519':
        raise Refused('bootstrap_signature_algorithm')
    try:
        pub = base64.b64decode(envelope['public_key_base64'], validate=True)
        signature = base64.b64decode(envelope['signature_base64'], validate=True)
        if len(pub) != 32 or len(signature) != 64 or digest(pub) != pinned_key:
            raise Refused('bootstrap_publisher_mismatch')
        signed = envelope['signed_payload']
        verify_signature(pub, signature, canonical(signed))
    except (ValueError, TypeError) as exc:
        raise Refused('bootstrap_signature_invalid') from exc
    fields = {'schema', 'sequence', 'issued_at', 'expires_at',
              'production_install_authorized', 'baseline_server_sha256',
              'baseline_launcher_sha256', 'candidate_server_sha256',
              'candidate_launcher_sha256', 'archive_sha256', 'archive_bytes',
              'data_migrations', 'validation'}
    if type(signed) is not dict or signed.keys() != fields:
        raise Refused('bootstrap_manifest_fields')
    current = int(time.time()) if now is None else now
    if (signed['schema'] != 'rapbrain-guarded-bootstrap-v1' or
            signed['production_install_authorized'] is not True or
            signed['data_migrations'] != [] or
            signed['validation'] != {'isolated_rollback': 'passed',
                                     'macos_runtime': 'passed'} or
            type(signed['sequence']) is not int or signed['sequence'] != 1 or
            type(signed['issued_at']) is not int or
            type(signed['expires_at']) is not int or
            not 0 <= signed['issued_at'] <= current < signed['expires_at']
            <= signed['issued_at'] + 31 * 86400 or
            type(signed['archive_bytes']) is not int or
            not 0 < signed['archive_bytes'] <= 2_000_000):
        raise Refused('bootstrap_not_authorized')
    for field in ('baseline_server_sha256', 'baseline_launcher_sha256',
                  'candidate_server_sha256', 'candidate_launcher_sha256',
                  'archive_sha256'):
        if type(signed[field]) is not str or not HEX.fullmatch(signed[field]):
            raise Refused('bootstrap_hash_format')
    if (type(original_server) is not bytes or type(original_launcher) is not bytes or
            digest(original_server) != signed['baseline_server_sha256'] or
            digest(original_launcher) != signed['baseline_launcher_sha256']):
        raise Refused('bootstrap_baseline_changed')
    if (type(archive_bytes) is not bytes or
            len(archive_bytes) != signed['archive_bytes'] or
            digest(archive_bytes) != signed['archive_sha256']):
        raise Refused('bootstrap_archive_integrity')
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            entries = archive.infolist()
            if (len(entries) != 2 or tuple(e.filename for e in entries) != FILES or
                    any(e.flag_bits & 1 or e.is_dir() or e.file_size > 1_000_000 or
                        stat.S_IFMT(e.external_attr >> 16) not in (0, stat.S_IFREG)
                        for e in entries)):
                raise Refused('bootstrap_archive_layout')
            files = {entry.filename: archive.read(entry) for entry in entries}
    except (zipfile.BadZipFile, RuntimeError, EOFError) as exc:
        raise Refused('bootstrap_archive_invalid') from exc
    if (digest(files['server.py']) != signed['candidate_server_sha256'] or
            digest(files['launch_manager.py']) != signed['candidate_launcher_sha256']):
        raise Refused('bootstrap_payload_changed')
    # The signature authorizes exactly our pinned minimal transformations.
    if (files['server.py'] != prepare_server(original_server) or
            files['launch_manager.py'] != prepare_launcher(original_launcher)):
        raise Refused('bootstrap_unexpected_code')
    return signed, files
