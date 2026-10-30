#!/usr/bin/env python3
"""Sign a production Creative Engine release locally; never export the key.

The only output is a public signed manifest copied to the clipboard. The
matching one-file ZIP is reproducible from the already verified P8 attachment.
No live code, SQLite, configuration, process or GitHub repository is changed.
"""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


P9_COMMIT = '445123c85c31c1133ce9582f2430b0cb37b76dea'
P9_SHA256 = '12dea538f86c42e8846d836e4f5b89373579a284a7d651e1956fed06e3879b09'
P9_URL = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
          + P9_COMMIT + '/manager-updater/mac_p9_isolated_gate.py')
PUBLIC = base64.b64decode('4/+1LuuUX672KFUyjOh083T/C7DaR8DLurYWQVimfzA=')
PIN = 'ae32610121418b50adcc8726df567a22ed7b3af67f804ef9aaaa7a1a4efce504'
SERVER = 'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27'
BASELINE = 'd68a0d8c175e533a84a16c0b9a5f922d51199be68a291cc0d1e32eac79938a0d'
PAYLOAD = 'b770bdf034caa600f75497325f80759d4f372258fa0e911e28f29d214abe85f3'
ARCHIVE_URL = 'https://albanherisson.github.io/rap-brain-updates/creative-stable/engine-1.zip'

SWIFT_SIGN = '''import Foundation
import CryptoKit
let args = CommandLine.arguments
guard args.count == 3,
  let keyBytes = try? Data(contentsOf: URL(fileURLWithPath: args[1])),
  let message = try? Data(contentsOf: URL(fileURLWithPath: args[2])) else { exit(2) }
let raw = keyBytes.count == 32 ? keyBytes :
  (Data(base64Encoded: String(data: keyBytes, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "") ?? Data())
guard raw.count == 32, let key = try? Curve25519.Signing.PrivateKey(rawRepresentation: raw) else { exit(3) }
let publicKey = key.publicKey.rawRepresentation
print(publicKey.base64EncodedString())
print(try key.signature(for: message).base64EncodedString())
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def one_file_archive(code):
    if sha(code) != PAYLOAD:
        raise ValueError('p8_payload_changed')
    info = zipfile.ZipInfo('creative_engine.py', (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as package:
        package.writestr(info, code)
    return stream.getvalue()


def production_payload(archive, *, now):
    if type(now) is not int or now < 1_700_000_000:
        raise ValueError('system_clock_invalid')
    return {'schema': 'rapbrain-creative-production-v1',
            'component': 'creative_engine', 'target': 'creative_engine.py',
            'sequence': 1, 'issued_at': now - 1,
            'expires_at': now + 14 * 86400,
            'production_install_authorized': True,
            'baseline_sha256': BASELINE, 'required_server_sha256': SERVER,
            'payload_sha256': PAYLOAD, 'archive_url': ARCHIVE_URL,
            'archive_sha256': sha(archive), 'archive_bytes': len(archive),
            'data_migrations': [],
            'validation': {'real_ollama': 'passed', 'full_server': 'passed'}}


def fetch_pinned_gate(folder):
    request = urllib.request.Request(P9_URL, headers={'Accept-Encoding': 'identity'})
    opener = urllib.request.build_opener(urllib.request.HTTPHandler,
                                        urllib.request.HTTPSHandler)
    with opener.open(request, timeout=30) as response:
        if response.status != 200 or response.geturl() != P9_URL:
            raise ValueError('p9_source_redirected')
        content = response.read(25_001)
    if sha(content) != P9_SHA256:
        raise ValueError('p9_source_changed')
    gate = folder / 'p9_gate.py'
    gate.write_bytes(content)
    spec = importlib.util.spec_from_file_location('p9_gate', gate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate_keys(home):
    support = home / 'Library' / 'Application Support'
    roots = [support, home / 'Downloads', home / 'Documents',
             home / '.config', home / '.local' / 'share',
             home / '.rapbrain', home / '.rap-brain',
             Path(tempfile.gettempdir()).resolve()]
    candidates = []
    override = os.environ.get('RAP_BRAIN_CREATIVE_KEY')
    if override:
        candidates.append(Path(override).expanduser())
    for root in roots:
        if root.is_symlink() or not root.is_dir():
            continue
        for directory, folders, files in os.walk(root, followlinks=False):
            current = Path(directory)
            depth = len(current.relative_to(root).parts)
            folders[:] = [name for name in folders if depth < 4 and
                not (current / name).is_symlink() and
                (depth != 0 or root not in (support, home / 'Downloads',
                   home / 'Documents', Path(tempfile.gettempdir()).resolve()) or
                 re.search(r'rap.?brain|creative|publisher|sign|key|p8', name, re.I))]
            for name in files:
                path = current / name
                if (re.search(r'key|ed25519|publisher|private|sign|creative|p8', name, re.I) and
                        path.suffix.lower() in ('', '.key', '.pem', '.bin', '.json',
                                                '.seed', '.txt', '.der')):
                    candidates.append(path)
                if len(candidates) > 200:
                    raise ValueError('publisher_key_search_limit')
    return dict.fromkeys(candidates)


def key_file(path):
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        return False
    try:
        info = path.stat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_size <= 4096 and info.st_size > 0
            and not info.st_mode & 0o077)


def sign_with_key(path, message, folder):
    if not key_file(path):
        return None
    raw = path.read_bytes()
    if raw.startswith(b'{'):
        try:
            record = json.loads(raw)
            value = next((record[name] for name in
                ('private_key_base64', 'seed_base64', 'private_key', 'seed')
                if type(record) is dict and type(record.get(name)) is str), None)
            raw = value.encode('ascii') if value is not None else b''
        except (ValueError, UnicodeError):
            return None
    if re.fullmatch(rb'[0-9a-fA-F]{64}\s*', raw):
        raw = bytes.fromhex(raw.strip().decode('ascii'))
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ModuleNotFoundError:
        target = folder / 'unsigned-manifest.json'
        target.write_bytes(message)
        try:
            result = subprocess.run(['/usr/bin/swift', '-e', SWIFT_SIGN,
                str(path), str(target)], stdin=subprocess.DEVNULL,
                capture_output=True, timeout=120)
        finally:
            target.unlink(missing_ok=True)
        if result.returncode or result.stderr:
            return None
        parts = result.stdout.splitlines()
        if len(parts) != 2:
            return None
        try:
            public, signature = (base64.b64decode(part, validate=True) for part in parts)
        except ValueError:
            return None
        return public, signature
    try:
        if len(raw) == 32:
            key = Ed25519PrivateKey.from_private_bytes(raw)
        elif re.fullmatch(rb'[A-Za-z0-9+/]{43}=\s*', raw):
            key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))
        elif raw.startswith(b'-----BEGIN '):
            key = serialization.load_pem_private_key(raw, password=None)
        else:
            key = serialization.load_der_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            return None
        return (key.public_key().public_bytes(serialization.Encoding.Raw,
                    serialization.PublicFormat.Raw), key.sign(message))
    except (ValueError, TypeError):
        return None


def sign_existing_identity(message, folder, *, home=None):
    home = Path.home() if home is None else home
    candidates = candidate_keys(home)
    safe = 0
    for path in candidates:
        if key_file(path):
            safe += 1
        signed = sign_with_key(path, message, folder)
        if signed is not None and signed[0] == PUBLIC:
            return signed[1]
    raise ValueError('p8_publisher_key_not_found candidates=' + str(len(candidates)) +
                     ' private_files=' + str(safe))


def make_envelope(payload, signature):
    if type(signature) is not bytes or len(signature) != 64:
        raise ValueError('invalid_publisher_signature')
    return canonical({'signed_payload': payload,
        'signature_algorithm': 'Ed25519',
        'signature_base64': base64.b64encode(signature).decode('ascii'),
        'public_key_base64': base64.b64encode(PUBLIC).decode('ascii')})


def main():
    if sys.platform != 'darwin' or sha(PUBLIC) != PIN:
        raise ValueError('mac_publisher_identity_required')
    with tempfile.TemporaryDirectory(prefix='rapbrain-creative-sign-') as temporary:
        folder = Path(temporary).resolve(strict=True)
        gate = fetch_pinned_gate(folder)
        code = gate.signed_candidate(folder)
        gate.pinned_file(gate.SOURCE / 'creative_engine.py', BASELINE)
        gate.pinned_file(gate.SOURCE / 'server.py', SERVER)
        archive = one_file_archive(code)
        payload = production_payload(archive, now=int(time.time()))
        signature = sign_existing_identity(canonical(payload), folder)
        envelope = make_envelope(payload, signature)
        gate.verify_signature(PUBLIC, signature, canonical(payload), folder)
        # Clipboard contains only the public release manifest, never the key.
        subprocess.run(['/usr/bin/pbcopy'], input=envelope,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=5)
    print('MANIFESTE CREATIVE SIGNE : OK')
    print('Signature publique copiée. Colle-la dans la conversation avec Cmd+V.')
    print('Aucun fichier actif modifié. Aucun paquet publié ou installé.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        detail = str(exc) if isinstance(exc, ValueError) else 'verification_failed'
        print('SIGNATURE CREATIVE REFUSEE : ' + detail, file=sys.stderr)
        raise SystemExit(2)
