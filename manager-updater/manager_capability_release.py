"""Authenticate the one-time Finder capability entirely before installation.

The release pins the Manager publisher and the installed post-Creative code.
Only the two UI files, ten reviewed app modules, and the external helper are
allowed. Neither this module nor its verifier writes the owner's app or data.
"""
import base64
import io
import re
import stat
import time
import zipfile

from bootstrap_release import PUBLISHER_PIN
from creative_release import Refused, canonical, digest
from ed25519_runtime import verify_signature
from manager_capability_inventory import APP_CODE_FILES
from manager_helper_release import verify_archive as verify_helper_archive
from manager_helper_release import verify_manifest as verify_helper_manifest
from manager_update_ui_candidate import LAUNCHER_SHA256, DASHBOARD_SHA256
from strict_json import parse_signed_json


SERVER_SHA256 = 'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27'
EXPECTED = tuple(sorted(['app/' + name for name in APP_CODE_FILES] + ['helper.zip']))
HEX = re.compile(r'[0-9a-f]{64}\Z')
MAX_ARCHIVE = 2_000_000
CHANNEL = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
           'main/manager-capability/manifest.json')
ARCHIVE = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
           'main/manager-capability/capability-1.zip')


def verify_release(raw, archive, *, pinned_key=PUBLISHER_PIN, now=None):
    if type(raw) is not bytes or not 0 < len(raw) <= 65536:
        raise Refused('manager_capability_manifest_size')
    envelope = parse_signed_json(raw)
    if (type(envelope) is not dict or envelope.keys() !=
            {'signed_payload', 'signature_algorithm', 'signature_base64',
             'public_key_base64'} or envelope['signature_algorithm'] != 'Ed25519'):
        raise Refused('manager_capability_envelope')
    try:
        public = base64.b64decode(envelope['public_key_base64'], validate=True)
        signature = base64.b64decode(envelope['signature_base64'], validate=True)
        if (len(public) != 32 or len(signature) != 64 or
                digest(public) != pinned_key):
            raise Refused('manager_capability_publisher_mismatch')
        signed = envelope['signed_payload']
        verify_signature(public, signature, canonical(signed))
    except Refused:
        raise
    except (TypeError, ValueError) as exc:
        raise Refused('manager_capability_signature_invalid') from exc
    current = int(time.time()) if now is None else now
    if (type(signed) is not dict or signed.keys() !=
            {'schema', 'sequence', 'issued_at', 'expires_at',
             'production_install_authorized', 'validation', 'data_migrations',
             'baseline_launcher_sha256', 'baseline_dashboard_sha256',
             'required_server_sha256', 'archive_url', 'archive_sha256',
             'archive_bytes', 'files', 'helper_manifest_base64'} or
            signed['schema'] != 'rapbrain-manager-capability-v1' or
            type(signed['sequence']) is not int or signed['sequence'] != 1 or
            signed['production_install_authorized'] is not True or
            signed['validation'] != {'macos_copy_install': 'passed',
                                     'rollback': 'passed', 'runtime': 'passed'} or
            signed['data_migrations'] != [] or
            type(signed['issued_at']) is not int or
            type(signed['expires_at']) is not int or
            not 0 <= signed['issued_at'] <= current < signed['expires_at'] <=
                signed['issued_at'] + 31 * 86400 or
            signed['baseline_launcher_sha256'] != LAUNCHER_SHA256 or
            signed['baseline_dashboard_sha256'] != DASHBOARD_SHA256 or
            signed['required_server_sha256'] != SERVER_SHA256 or
            signed['archive_url'] != ARCHIVE or
            type(signed['archive_bytes']) is not int or
            not 0 < signed['archive_bytes'] <= MAX_ARCHIVE or
            type(signed['archive_sha256']) is not str or
            not HEX.fullmatch(signed['archive_sha256']) or
            type(signed['files']) is not dict or
            tuple(sorted(signed['files'])) != EXPECTED or
            any(type(value) is not str or not HEX.fullmatch(value)
                for value in signed['files'].values()) or
            type(signed['helper_manifest_base64']) is not str or
            len(signed['helper_manifest_base64']) > 32_000):
        raise Refused('manager_capability_scope')
    try:
        helper_signed = base64.b64decode(signed['helper_manifest_base64'],
                                         validate=True)
    except ValueError as exc:
        raise Refused('manager_capability_helper_manifest_invalid') from exc
    helper = verify_helper_manifest(helper_signed, pinned_key=pinned_key,
                                    now=current)
    if helper['archive_sha256'] != signed['files']['helper.zip']:
        raise Refused('manager_capability_helper_mismatch')
    if (type(archive) is not bytes or len(archive) != signed['archive_bytes'] or
            digest(archive) != signed['archive_sha256']):
        raise Refused('manager_capability_archive_integrity')
    files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            members = zipped.infolist()
            if ([item.filename for item in members] != list(EXPECTED) or
                    any(item.flag_bits & 1 or item.is_dir() or
                        item.compress_type != zipfile.ZIP_DEFLATED or
                        not 0 < item.file_size <= 1_000_000 or
                        stat.S_IFMT(item.external_attr >> 16) != stat.S_IFREG
                        for item in members) or
                    sum(item.file_size for item in members) > MAX_ARCHIVE):
                raise Refused('manager_capability_archive_layout')
            for item in members:
                value = zipped.read(item)
                if digest(value) != signed['files'][item.filename]:
                    raise Refused('manager_capability_member_changed')
                if item.filename.endswith('.py'):
                    compile(value, item.filename, 'exec')
                elif item.filename.endswith('.html'):
                    value.decode('utf-8')
                files[item.filename] = value
    except (zipfile.BadZipFile, EOFError, RuntimeError, SyntaxError,
            UnicodeError) as exc:
        raise Refused('manager_capability_archive_invalid') from exc
    verify_helper_archive(files['helper.zip'], helper)
    return signed, files, helper_signed
