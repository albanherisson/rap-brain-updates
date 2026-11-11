"""Ed25519 verifier using Python crypto or the existing macOS CryptoKit runtime.

The private key is never accessed. A bad signature never falls back to another
trust identity; the caller must pin the public-key fingerprint first.
"""
import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def verify_signature(pub, signature, message):
    if (type(pub) is not bytes or len(pub) != 32 or
            type(signature) is not bytes or len(signature) != 64 or
            type(message) is not bytes or len(message) > 65536):
        raise ValueError('ed25519_input_invalid')
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ModuleNotFoundError:
        if sys.platform != 'darwin':
            raise ValueError('ed25519_verifier_unavailable')
        verifier = Path(__file__).with_name('verify_ed25519.swift')
        if verifier.is_symlink() or not verifier.is_file():
            raise ValueError('cryptokit_verifier_missing')
        with tempfile.TemporaryDirectory(prefix='rapbrain-ed25519-') as name:
            path = Path(name) / 'message'
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(message)
            except BaseException:
                if os.path.exists(path):
                    path.unlink()
                raise
            try:
                result = subprocess.run(['/usr/bin/swift', str(verifier),
                    base64.b64encode(pub).decode('ascii'),
                    base64.b64encode(signature).decode('ascii'), str(path)],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=90)
            except (OSError, subprocess.SubprocessError) as exc:
                raise ValueError('cryptokit_verifier_unavailable') from exc
            if result.returncode != 0 or result.stdout or result.stderr:
                raise ValueError('ed25519_signature_invalid')
    else:
        from cryptography.exceptions import InvalidSignature
        try:
            Ed25519PublicKey.from_public_bytes(pub).verify(signature, message)
        except InvalidSignature as exc:
            raise ValueError('ed25519_signature_invalid') from exc
    return True
