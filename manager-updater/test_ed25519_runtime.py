import builtins
import sys
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ed25519_runtime import verify_signature


class Ed25519RuntimeTests(unittest.TestCase):
    def test_python_verifier_accepts_signature_and_rejects_tampering(self):
        key = Ed25519PrivateKey.generate()
        pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        signature = key.sign(b'signed candidate')
        self.assertTrue(verify_signature(pub, signature, b'signed candidate'))
        with self.assertRaisesRegex(ValueError, 'signature_invalid'):
            verify_signature(pub, signature, b'altered candidate')

    @unittest.skipUnless(sys.platform == 'darwin', 'CryptoKit requires macOS')
    def test_cryptokit_fallback_without_python_crypto(self):
        key = Ed25519PrivateKey.generate()
        pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        signature = key.sign(b'candidate on Mac')
        original_import = builtins.__import__

        def missing_crypto(name, *args, **kwargs):
            if name == 'cryptography.hazmat.primitives.asymmetric.ed25519':
                raise ModuleNotFoundError(name)
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=missing_crypto):
            self.assertTrue(verify_signature(pub, signature, b'candidate on Mac'))
            with self.assertRaisesRegex(ValueError, 'signature_invalid'):
                verify_signature(pub, signature, b'altered on Mac')


if __name__ == '__main__':
    unittest.main()
