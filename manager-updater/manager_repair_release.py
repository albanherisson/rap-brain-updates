"""Authenticate the narrow, offline Manager handoff repair in memory.

The signed archive contains source and helper bytes only. A trusted macOS
compiler builds the native executable on a disposable app copy before any
live change. This module has no installation or database access.
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
from manager_helper_release import verify_archive as helper_archive
from manager_helper_release import verify_manifest as helper_manifest
from strict_json import parse_signed_json


CHANNEL = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
           'main/manager-repair/manifest.json')
ARCHIVE = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
           'main/manager-repair/repair-1.zip')
FILES = ('app/RapBrainManagerNative.swift', 'app/launch_manager.py', 'helper.zip')
LAUNCHER = 'e072f29f2416ed286c67f8faa73f517a1fb5deafb20cf125ac8f8417722a6464'
NATIVE_SOURCE = 'd996f4812cd612241d39dea9595d06903754372e4664b7c1b95ced6deae91b68'
OLD_HELPER = '3e296b07df6bbb903c82de56167b429a34800a7c92131cd50a1ef2c08f458168'
SERVER = 'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27'
HEX = re.compile(r'[0-9a-f]{64}\Z')
MAX_ARCHIVE = 2_000_000


def verify_release(raw, archive, *, pinned_key=PUBLISHER_PIN, now=None):
    if type(raw) is not bytes or not 0 < len(raw) <= 65536:
        raise Refused('manager_repair_manifest_size')
    envelope = parse_signed_json(raw)
    if (type(envelope) is not dict or envelope.keys() !=
            {'signed_payload', 'signature_algorithm', 'signature_base64',
             'public_key_base64'} or envelope['signature_algorithm'] != 'Ed25519'):
        raise Refused('manager_repair_envelope')
    try:
        public = base64.b64decode(envelope['public_key_base64'], validate=True)
        signature = base64.b64decode(envelope['signature_base64'], validate=True)
        if (len(public) != 32 or len(signature) != 64 or
                digest(public) != pinned_key):
            raise Refused('manager_repair_publisher_mismatch')
        signed = envelope['signed_payload']
        verify_signature(public, signature, canonical(signed))
    except Refused:
        raise
    except (TypeError, ValueError) as exc:
        raise Refused('manager_repair_signature_invalid') from exc
    current = int(time.time()) if now is None else now
    if (type(signed) is not dict or signed.keys() !=
            {'schema', 'sequence', 'issued_at', 'expires_at', 'validation',
             'production_install_authorized', 'data_migrations',
             'baseline_launcher_sha256', 'baseline_native_source_sha256',
             'baseline_helper_sha256', 'required_server_sha256',
             'archive_url', 'archive_sha256', 'archive_bytes', 'files',
             'helper_manifest_base64'} or
            signed['schema'] != 'rapbrain-manager-repair-v1' or
            signed['sequence'] != 2 or
            signed['production_install_authorized'] is not True or
            signed['data_migrations'] != [] or
            signed['validation'] != {'macos_copy_install': 'passed',
                                     'rollback': 'passed', 'runtime': 'passed'} or
            signed['baseline_launcher_sha256'] != LAUNCHER or
            signed['baseline_native_source_sha256'] != NATIVE_SOURCE or
            signed['baseline_helper_sha256'] != OLD_HELPER or
            signed['required_server_sha256'] != SERVER or
            signed['archive_url'] != ARCHIVE or
            type(signed['issued_at']) is not int or
            type(signed['expires_at']) is not int or
            not 0 <= signed['issued_at'] <= current < signed['expires_at'] <=
                signed['issued_at'] + 31 * 86400 or
            type(signed['archive_bytes']) is not int or
            not 0 < signed['archive_bytes'] <= MAX_ARCHIVE or
            type(signed['archive_sha256']) is not str or
            not HEX.fullmatch(signed['archive_sha256']) or
            type(signed['files']) is not dict or
            tuple(sorted(signed['files'])) != FILES or
            any(type(v) is not str or not HEX.fullmatch(v)
                for v in signed['files'].values()) or
            type(signed['helper_manifest_base64']) is not str or
            len(signed['helper_manifest_base64']) > 32_000):
        raise Refused('manager_repair_scope')
    try:
        helper_signed = base64.b64decode(signed['helper_manifest_base64'],
                                         validate=True)
    except ValueError as exc:
        raise Refused('manager_repair_helper_manifest') from exc
    helper = helper_manifest(helper_signed, pinned_key=pinned_key, now=current)
    if (helper['sequence'] != 2 or
            helper['archive_sha256'] != signed['files']['helper.zip']):
        raise Refused('manager_repair_helper_mismatch')
    if (type(archive) is not bytes or len(archive) != signed['archive_bytes'] or
            digest(archive) != signed['archive_sha256']):
        raise Refused('manager_repair_archive_integrity')
    files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            members = zipped.infolist()
            if ([item.filename for item in members] != list(FILES) or
                    any(item.flag_bits & 1 or item.is_dir() or
                        item.compress_type != zipfile.ZIP_DEFLATED or
                        not 0 < item.file_size <= 1_000_000 or
                        stat.S_IFMT(item.external_attr >> 16) != stat.S_IFREG
                        for item in members)):
                raise Refused('manager_repair_archive_layout')
            for item in members:
                data = zipped.read(item)
                if digest(data) != signed['files'][item.filename]:
                    raise Refused('manager_repair_member_changed')
                if item.filename.endswith('.py'):
                    compile(data, item.filename, 'exec')
                elif item.filename.endswith('.swift'):
                    source = data.decode('utf-8')
                    if ('import AppKit' not in source or
                            'proc.terminationStatus == 42' not in source):
                        raise Refused('manager_repair_native_scope')
                files[item.filename] = data
    except (zipfile.BadZipFile, EOFError, RuntimeError, SyntaxError,
            UnicodeError) as exc:
        raise Refused('manager_repair_archive_invalid') from exc
    helper_archive(files['helper.zip'], helper)
    return signed, files, helper_signed
