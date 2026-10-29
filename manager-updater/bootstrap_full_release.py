"""Verify a single signed guarded bootstrap with the complete app runtime.

This is a verifier only. No production release has been signed or installed.
The older two-file bootstrap verifier is a copy-only precursor.
"""
import base64
import io
import stat
import time
from urllib.parse import urlsplit
import zipfile

from beta14_one_click_candidate import prepare_dashboard, prepare_launcher
from bootstrap_release import PUBLISHER_PIN
from bootstrap_runtime_resources import RUNTIME_FILES, verify_runtime_resources
from creative_release import Refused, canonical, digest
from ed25519_runtime import verify_signature
from recovery_start_guards import prepare_server
from strict_json import parse_signed_json


PRIMARY = ('server.py', 'launch_manager.py', 'dashboard_beta14.html')
FILES = PRIMARY + RUNTIME_FILES
HEX = set('0123456789abcdef')
CHANNEL = 'https://albanherisson.github.io/rap-brain-updates/manager-bootstrap/manifest.json'


def hex_digest(value):
    return type(value) is str and len(value) == 64 and set(value) <= HEX


def allowed_archive_url(url):
    if type(url) is not str:
        raise Refused('bootstrap_archive_url')
    parsed = urlsplit(url)
    name = parsed.path.removeprefix('/rap-brain-updates/manager-bootstrap/')
    if (parsed.scheme != 'https' or parsed.netloc != 'albanherisson.github.io' or
            parsed.query or parsed.fragment or
            parsed.path != '/rap-brain-updates/manager-bootstrap/' + name or
            not 1 <= len(name) <= 80 or not name.endswith('.zip') or
            any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.'
                for c in name)):
        raise Refused('bootstrap_archive_url')
    return url


def verify_full_manifest(manifest_bytes, original_server, original_launcher,
                         original_dashboard, *, pinned_key=PUBLISHER_PIN, now=None):
    if type(manifest_bytes) is not bytes or not 0 < len(manifest_bytes) <= 65536:
        raise Refused('bootstrap_manifest_size')
    envelope = parse_signed_json(manifest_bytes)
    if (type(envelope) is not dict or envelope.keys() !=
            {'signed_payload', 'signature_algorithm', 'signature_base64', 'public_key_base64'} or
            envelope['signature_algorithm'] != 'Ed25519'):
        raise Refused('bootstrap_envelope')
    try:
        public = base64.b64decode(envelope['public_key_base64'], validate=True)
        signature = base64.b64decode(envelope['signature_base64'], validate=True)
        if len(public) != 32 or len(signature) != 64 or digest(public) != pinned_key:
            raise Refused('bootstrap_publisher_mismatch')
        signed = envelope['signed_payload']
        verify_signature(public, signature, canonical(signed))
    except Refused:
        raise
    except (ValueError, TypeError) as exc:
        raise Refused('bootstrap_signature_invalid') from exc
    fields = {'schema', 'sequence', 'issued_at', 'expires_at',
              'production_install_authorized', 'data_migrations', 'validation',
              'baseline_server_sha256', 'baseline_launcher_sha256',
              'baseline_dashboard_sha256', 'candidate_server_sha256',
              'candidate_launcher_sha256', 'candidate_dashboard_sha256',
              'runtime_sha256', 'archive_url', 'archive_sha256', 'archive_bytes'}
    current = int(time.time()) if now is None else now
    if (type(signed) is not dict or signed.keys() != fields or
            signed['schema'] != 'rapbrain-guarded-bootstrap-v2' or
            signed['production_install_authorized'] is not True or
            signed['data_migrations'] != [] or
            signed['validation'] != {'isolated_rollback': 'passed',
                                     'macos_runtime': 'passed'} or
            type(signed['sequence']) is not int or signed['sequence'] != 1 or
            type(signed['issued_at']) is not int or
            type(signed['expires_at']) is not int or
            not 0 <= signed['issued_at'] <= current < signed['expires_at'] <=
                    signed['issued_at'] + 31 * 86400 or
            type(signed['archive_bytes']) is not int or
            not 0 < signed['archive_bytes'] <= 2_000_000):
        raise Refused('bootstrap_not_authorized')
    for name in ('server', 'launcher', 'dashboard'):
        if (not hex_digest(signed['baseline_' + name + '_sha256']) or
                not hex_digest(signed['candidate_' + name + '_sha256'])):
            raise Refused('bootstrap_hash_format')
    if not hex_digest(signed['archive_sha256']):
        raise Refused('bootstrap_hash_format')
    allowed_archive_url(signed['archive_url'])
    originals = (original_server, original_launcher, original_dashboard)
    if any(type(raw) is not bytes or digest(raw) != signed['baseline_' + name + '_sha256']
           for raw, name in zip(originals, ('server', 'launcher', 'dashboard'))):
        raise Refused('bootstrap_baseline_changed')
    return signed


def verify_full_bootstrap(manifest_bytes, archive_bytes, original_server,
                          original_launcher, original_dashboard, *,
                          pinned_key=PUBLISHER_PIN, now=None):
    signed = verify_full_manifest(manifest_bytes, original_server, original_launcher,
                                  original_dashboard, pinned_key=pinned_key, now=now)
    if (type(archive_bytes) is not bytes or
            len(archive_bytes) != signed['archive_bytes'] or
            digest(archive_bytes) != signed['archive_sha256']):
        raise Refused('bootstrap_archive_integrity')
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            entries = archive.infolist()
            if (tuple(entry.filename for entry in entries) != FILES or
                    any(entry.flag_bits & 1 or entry.is_dir() or
                        entry.file_size > 250_000 or
                        stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                        for entry in entries)):
                raise Refused('bootstrap_archive_layout')
            files = {entry.filename: archive.read(entry) for entry in entries}
    except (zipfile.BadZipFile, RuntimeError, EOFError) as exc:
        raise Refused('bootstrap_archive_invalid') from exc
    if any(digest(files[path]) != signed['candidate_' + name + '_sha256']
           for path, name in zip(PRIMARY, ('server', 'launcher', 'dashboard'))):
        raise Refused('bootstrap_payload_changed')
    verify_runtime_resources({name: files[name] for name in RUNTIME_FILES},
                             signed['runtime_sha256'])
    if (files['server.py'] != prepare_server(original_server) or
            files['launch_manager.py'] != prepare_launcher(original_launcher) or
            files['dashboard_beta14.html'] != prepare_dashboard(original_dashboard)):
        raise Refused('bootstrap_unexpected_code')
    return signed, files
