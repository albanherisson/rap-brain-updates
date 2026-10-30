"""Verify a Manager-authorized rotation of the Creative publisher key.

Pure byte verification: this module neither discovers an app nor writes files.
The installer must separately prove idle processes, backup, app signature,
atomic replacement and exact rollback before using the returned candidate.
"""
import base64
import hashlib
import re
import time

from bootstrap_release import PUBLISHER_PIN
from creative_release import CREATIVE_KEY_PIN, Refused, canonical
from ed25519_runtime import verify_signature
from strict_json import parse_signed_json


BASELINE_SHA256 = 'b50195f6665baefd1838f5aec2e750ed33504804d80c6f09bd493aa20ce779a9'
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
MARKER = ("CREATIVE_KEY_PIN = '" + CREATIVE_KEY_PIN + "'").encode('ascii')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def candidate_for_key(original, new_public_key):
    """Only the pinned fingerprint may differ from the installed file."""
    if type(original) is not bytes or digest(original) != BASELINE_SHA256:
        raise Refused('trust_rotation_baseline_changed')
    if type(new_public_key) is not bytes or len(new_public_key) != 32:
        raise Refused('trust_rotation_public_key')
    pin = digest(new_public_key)
    if pin in (PUBLISHER_PIN, CREATIVE_KEY_PIN):
        raise Refused('trust_rotation_key_not_distinct')
    if original.count(MARKER) != 1:
        raise Refused('trust_rotation_marker_changed')
    candidate = original.replace(MARKER, ("CREATIVE_KEY_PIN = '" + pin + "'").encode('ascii'))
    compile(candidate, 'creative_release.py', 'exec')
    return candidate


def verify_rotation(manifest, original, *, now=None):
    """Return (signed payload, new file bytes) after all signature/hash checks."""
    if type(manifest) is not bytes or not 0 < len(manifest) <= 16_384:
        raise Refused('trust_rotation_manifest_size')
    envelope = parse_signed_json(manifest)
    if type(envelope) is not dict or set(envelope) != {
            'signed_payload', 'signature_algorithm', 'signature_base64', 'public_key_base64'}:
        raise Refused('trust_rotation_envelope')
    if envelope['signature_algorithm'] != 'Ed25519':
        raise Refused('trust_rotation_algorithm')
    try:
        publisher = base64.b64decode(envelope['public_key_base64'], validate=True)
        signature = base64.b64decode(envelope['signature_base64'], validate=True)
        if len(publisher) != 32 or len(signature) != 64 or digest(publisher) != PUBLISHER_PIN:
            raise Refused('trust_rotation_publisher')
        signed = envelope['signed_payload']
        verify_signature(publisher, signature, canonical(signed))
    except (ValueError, TypeError) as exc:
        raise Refused('trust_rotation_signature') from exc
    fields = {'schema', 'sequence', 'issued_at', 'expires_at',
              'production_install_authorized', 'target', 'baseline_sha256',
              'candidate_sha256', 'new_public_key_base64', 'new_public_key_sha256',
              'data_migrations'}
    current = int(time.time()) if now is None else now
    if (type(signed) is not dict or set(signed) != fields or
            signed['schema'] != 'rapbrain-creative-trust-rotation-v1' or
            signed['sequence'] != 1 or type(signed['sequence']) is not int or
            signed['production_install_authorized'] is not True or
            signed['target'] != 'creative_release.py' or
            signed['data_migrations'] != [] or
            type(signed['issued_at']) is not int or
            type(signed['expires_at']) is not int or
            not 0 <= signed['issued_at'] <= current < signed['expires_at'] <=
            signed['issued_at'] + 31 * 86400 or
            signed['baseline_sha256'] != BASELINE_SHA256):
        raise Refused('trust_rotation_scope')
    if any(type(signed[name]) is not str or not SHA256.fullmatch(signed[name])
           for name in ('candidate_sha256', 'new_public_key_sha256')):
        raise Refused('trust_rotation_hash_format')
    try:
        key = base64.b64decode(signed['new_public_key_base64'], validate=True)
    except (ValueError, TypeError) as exc:
        raise Refused('trust_rotation_public_key') from exc
    candidate = candidate_for_key(original, key)
    if digest(key) != signed['new_public_key_sha256'] or digest(candidate) != signed['candidate_sha256']:
        raise Refused('trust_rotation_candidate_hash')
    return signed, candidate
