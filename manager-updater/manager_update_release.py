"""Verify a signed Manager/server release entirely in memory.

The transaction and app handoff are separate. This module has no write or
execution path, and refuses every database, model and library path.
"""
import base64
import io
import re
import stat
import time
from urllib.parse import urlsplit
import urllib.request
import zipfile

from bootstrap_release import PUBLISHER_PIN
from bootstrap_runtime_resources import RUNTIME_FILES
from creative_release import Refused, canonical, digest
from ed25519_runtime import verify_signature
from strict_json import parse_signed_json


CHANNEL = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
           'main/manager-stable/manifest.json')
ALLOWED = frozenset(('server.py', 'app/launch_manager.py',
                     'app/dashboard_beta14.html') +
                    tuple('app/' + name for name in RUNTIME_FILES))
HEX = re.compile(r'[0-9a-f]{64}\Z')
MAX_ARCHIVE = 2_000_000
MAX_MEMBER = 250_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise Refused('manager_redirect_refused')


def fetch(url, limit):
    if url != CHANNEL:
        archive_url(url)
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(url, headers={
            'Accept-Encoding': 'identity'}), timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise Refused('manager_unexpected_response')
        raw = response.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise Refused('manager_download_size')
    return raw


def archive_url(value):
    if type(value) is not str:
        raise Refused('manager_archive_url')
    parsed = urlsplit(value)
    prefix = '/albanherisson/rap-brain-updates/main/manager-stable/'
    name = parsed.path.removeprefix(prefix)
    if (parsed.scheme != 'https' or parsed.netloc != 'raw.githubusercontent.com'
            or parsed.query or parsed.fragment or parsed.path != prefix + name
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,72}\.zip', name)):
        raise Refused('manager_archive_url')
    return value


def verify_manifest(raw, *, minimum_sequence=0, now=None,
                    pinned_key=PUBLISHER_PIN):
    if type(raw) is not bytes or not 0 < len(raw) <= 65536:
        raise Refused('manager_manifest_size')
    envelope = parse_signed_json(raw)
    if (type(envelope) is not dict or envelope.keys() !=
            {'signed_payload', 'signature_algorithm', 'signature_base64',
             'public_key_base64'} or envelope['signature_algorithm'] != 'Ed25519'):
        raise Refused('manager_envelope')
    try:
        public = base64.b64decode(envelope['public_key_base64'], validate=True)
        signature = base64.b64decode(envelope['signature_base64'], validate=True)
        if (len(public) != 32 or len(signature) != 64 or
                digest(public) != pinned_key):
            raise Refused('manager_publisher_mismatch')
        signed = envelope['signed_payload']
        verify_signature(public, signature, canonical(signed))
    except Refused:
        raise
    except (ValueError, TypeError) as exc:
        raise Refused('manager_signature_invalid') from exc
    if (type(signed) is not dict or signed.keys() !=
            {'schema', 'sequence', 'issued_at', 'expires_at',
             'production_install_authorized', 'data_migrations', 'validation',
             'files', 'archive_url', 'archive_sha256', 'archive_bytes'} or
            signed['schema'] != 'rapbrain-manager-production-v1' or
            signed['production_install_authorized'] is not True or
            signed['data_migrations'] != [] or
            signed['validation'] != {'macos_copy_install': 'passed',
                                     'rollback': 'passed', 'runtime': 'passed'}):
        raise Refused('manager_release_scope')
    current = int(time.time()) if now is None else now
    if (type(signed['sequence']) is not int or
            signed['sequence'] <= minimum_sequence or
            type(signed['issued_at']) is not int or
            type(signed['expires_at']) is not int or
            not 0 <= signed['issued_at'] <= current < signed['expires_at'] <=
                signed['issued_at'] + 31 * 86400 or
            type(signed['archive_bytes']) is not int or
            not 0 < signed['archive_bytes'] <= MAX_ARCHIVE or
            type(signed['archive_sha256']) is not str or
            not HEX.fullmatch(signed['archive_sha256'])):
        raise Refused('manager_release_freshness')
    entries = signed['files']
    if type(entries) is not list or not 0 < len(entries) <= len(ALLOWED):
        raise Refused('manager_file_inventory')
    names = []
    for entry in entries:
        if (type(entry) is not dict or entry.keys() !=
                {'path', 'baseline_sha256', 'payload_sha256'} or
                type(entry['path']) is not str or entry['path'] not in ALLOWED or
                any(type(entry[key]) is not str or not HEX.fullmatch(entry[key])
                    for key in ('baseline_sha256', 'payload_sha256')) or
                entry['baseline_sha256'] == entry['payload_sha256']):
            raise Refused('manager_file_scope')
        names.append(entry['path'])
    if names != sorted(set(names)):
        raise Refused('manager_file_order')
    archive_url(signed['archive_url'])
    return signed


def verify_archive(raw, manifest):
    if (type(raw) is not bytes or len(raw) != manifest['archive_bytes'] or
            digest(raw) != manifest['archive_sha256']):
        raise Refused('manager_archive_integrity')
    expected = [entry['path'] for entry in manifest['files']]
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if ([member.filename for member in members] != expected or
                    any(member.flag_bits & 1 or member.is_dir() or
                        not 0 < member.file_size <= MAX_MEMBER or
                        stat.S_IFMT(member.external_attr >> 16) not in
                            (0, stat.S_IFREG) for member in members)):
                raise Refused('manager_archive_layout')
            files = {}
            for member, entry in zip(members, manifest['files']):
                with archive.open(member) as stream:
                    code = stream.read(MAX_MEMBER + 1)
                if (len(code) != member.file_size or
                        digest(code) != entry['payload_sha256']):
                    raise Refused('manager_payload_integrity')
                if member.filename.endswith('.py'):
                    compile(code, member.filename, 'exec')
                else:
                    code.decode('utf-8')
                files[member.filename] = code
    except (zipfile.BadZipFile, EOFError, RuntimeError, UnicodeError,
            SyntaxError) as exc:
        raise Refused('manager_archive_invalid') from exc
    return files


def download_release(*, minimum_sequence=0, downloader=fetch,
                     pinned_key=PUBLISHER_PIN):
    """Authenticate the manifest before requesting any executable payload."""
    raw = downloader(CHANNEL, 65536)
    manifest = verify_manifest(raw, minimum_sequence=minimum_sequence,
                               pinned_key=pinned_key)
    archive = downloader(manifest['archive_url'], MAX_ARCHIVE)
    return raw, archive, verify_archive(archive, manifest)
