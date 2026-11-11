"""Read-only production release gate for the Creative Engine.

P8 rehearsal signatures and legacy Manager signatures are deliberately NOT
production releases. No private key, extraction, import or execution here.
"""
import base64
import hashlib
import io
import json
import re
import stat
import time
import urllib.request
from urllib.parse import urlsplit
import zipfile

from strict_json import parse_signed_json
from ed25519_runtime import verify_signature

# Fingerprint already pinned and verified by Beta 14 / P10 on the owner's Mac.
CREATIVE_KEY_PIN = 'ae32610121418b50adcc8726df567a22ed7b3af67f804ef9aaaa7a1a4efce504'
CHANNEL_URL = 'https://albanherisson.github.io/rap-brain-updates/creative-stable/manifest.json'
MAX_ARCHIVE = 2_000_000
MAX_CODE = 1_000_000
HASH = re.compile(r'[0-9a-f]{64}\Z')


class Refused(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def allowed_url(url):
    if not isinstance(url, str):
        raise Refused('missing_url')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'albanherisson.github.io'
            or parsed.query or parsed.fragment
            or not re.fullmatch(r'/rap-brain-updates/creative-stable/[A-Za-z0-9_-]+\.(?:json|zip)', parsed.path)):
        raise Refused('untrusted_distribution_url')
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refused('redirect_refused')


def fetch(url, limit):
    allowed_url(url)
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(url, headers={'Accept-Encoding': 'identity'}), timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise Refused('unexpected_response')
        data = response.read(limit + 1)
    if not 0 < len(data) <= limit:
        raise Refused('download_size_limit')
    return data


def verify_manifest(raw, *, minimum_sequence=0, now=None, pinned_key=CREATIVE_KEY_PIN):
    envelope = parse_signed_json(raw)
    if not isinstance(envelope, dict) or set(envelope) != {
            'signed_payload', 'signature_algorithm', 'signature_base64', 'public_key_base64'}:
        raise Refused('invalid_envelope')
    if envelope['signature_algorithm'] != 'Ed25519':
        raise Refused('signature_algorithm')
    pub = base64.b64decode(envelope['public_key_base64'], validate=True)
    if digest(pub) != pinned_key:
        raise Refused('publisher_key_mismatch')
    signed = envelope['signed_payload']
    verify_signature(pub, base64.b64decode(envelope['signature_base64'], validate=True),
                     canonical(signed))
    fields = {'schema', 'component', 'target', 'sequence', 'issued_at', 'expires_at',
              'production_install_authorized', 'baseline_sha256', 'required_server_sha256',
              'payload_sha256', 'archive_url', 'archive_sha256', 'archive_bytes',
              'data_migrations', 'validation'}
    if not isinstance(signed, dict) or set(signed) != fields:
        raise Refused('production_manifest_required')
    if (signed['schema'] != 'rapbrain-creative-production-v1'
            or signed['component'] != 'creative_engine' or signed['target'] != 'creative_engine.py'
            or signed['production_install_authorized'] is not True
            or signed['data_migrations'] != []):
        raise Refused('production_scope_refused')
    if signed['validation'] != {'real_ollama': 'passed', 'full_server': 'passed'}:
        raise Refused('runtime_validation_missing')
    for key in ('sequence', 'issued_at', 'expires_at', 'archive_bytes'):
        if type(signed[key]) is not int:
            raise Refused('integer_required')
    now = int(time.time()) if now is None else now
    if not (signed['sequence'] > minimum_sequence and 0 <= signed['issued_at'] <= now
            < signed['expires_at'] <= signed['issued_at'] + 31 * 86400):
        raise Refused('stale_or_expired_release')
    if not 0 < signed['archive_bytes'] <= MAX_ARCHIVE:
        raise Refused('archive_size')
    for key in ('baseline_sha256', 'required_server_sha256', 'payload_sha256', 'archive_sha256'):
        if not isinstance(signed[key], str) or not HASH.fullmatch(signed[key]):
            raise Refused('hash_format')
    if signed['baseline_sha256'] == signed['payload_sha256']:
        raise Refused('unchanged_candidate')
    allowed_url(signed['archive_url'])
    return signed


def verify_archive(raw, manifest):
    if len(raw) != manifest['archive_bytes'] or digest(raw) != manifest['archive_sha256']:
        raise Refused('archive_integrity')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) != 1 or entries[0].filename != 'creative_engine.py':
            raise Refused('unexpected_zip_layout')
        entry = entries[0]
        if (entry.flag_bits & 1 or entry.is_dir() or entry.file_size > MAX_CODE
                or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)):
            raise Refused('unsafe_zip_member')
        with archive.open(entry) as stream:
            code = stream.read(MAX_CODE + 1)
        if len(code) != entry.file_size or digest(code) != manifest['payload_sha256']:
            raise Refused('payload_integrity')
    # Compile in memory; no import, subprocess or pycache in the active tree.
    compile(code, 'creative_engine.py', 'exec')
    return code


def download_release(*, minimum_sequence=0):
    raw = fetch(CHANNEL_URL, 65536)
    manifest = verify_manifest(raw, minimum_sequence=minimum_sequence)
    archive = fetch(manifest['archive_url'], MAX_ARCHIVE)
    verify_archive(archive, manifest)
    return raw, archive
