import base64
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import creative_trust_rotation as rotation
from creative_release import Refused, canonical


class TrustRotationTests(unittest.TestCase):
    def setUp(self):
        self.original = Path(__file__).with_name('creative_release.py').read_bytes()
        self.publisher = Ed25519PrivateKey.generate()
        self.publisher_public = self.publisher.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.new_key = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.candidate = rotation.candidate_for_key(self.original, self.new_key)
        now = int(time.time())
        self.payload = {
            'schema': 'rapbrain-creative-trust-rotation-v1', 'sequence': 1,
            'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True, 'target': 'creative_release.py',
            'baseline_sha256': rotation.digest(self.original),
            'candidate_sha256': rotation.digest(self.candidate),
            'new_public_key_base64': base64.b64encode(self.new_key).decode('ascii'),
            'new_public_key_sha256': rotation.digest(self.new_key),
            'data_migrations': []}

    def envelope(self, payload=None, publisher=None):
        payload = self.payload if payload is None else payload
        publisher = self.publisher if publisher is None else publisher
        public = publisher.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return canonical({'signed_payload': payload, 'signature_algorithm': 'Ed25519',
                          'public_key_base64': base64.b64encode(public).decode('ascii'),
                          'signature_base64': base64.b64encode(
                              publisher.sign(canonical(payload))).decode('ascii')})

    def verified(self, manifest=None, source=None):
        with patch.object(rotation, 'PUBLISHER_PIN', rotation.digest(self.publisher_public)):
            return rotation.verify_rotation(self.envelope() if manifest is None else manifest,
                                            self.original if source is None else source)

    def test_exact_one_line_rotation(self):
        payload, candidate = self.verified()
        self.assertEqual(payload, self.payload)
        self.assertEqual(candidate, self.candidate)
        self.assertEqual(candidate.count(rotation.digest(self.new_key).encode()), 1)
        self.assertNotIn(rotation.CREATIVE_KEY_PIN.encode(), candidate)

    def test_refuses_tampering_or_scope_expansion(self):
        for change in ({'target': 'server.py'}, {'data_migrations': ['sqlite']},
                       {'production_install_authorized': False},
                       {'candidate_sha256': '0' * 64}, {'expires_at': 1},
                       {'new_public_key_sha256': '0' * 64}):
            with self.subTest(change=change), self.assertRaises(Refused):
                self.verified(self.envelope(self.payload | change))
        forged = json.loads(self.envelope())
        forged['signed_payload']['candidate_sha256'] = '0' * 64
        with self.assertRaises(Refused):
            self.verified(canonical(forged))
        with self.assertRaises(Refused):
            self.verified(source=self.original + b'\n')

    def test_refuses_wrong_publisher_and_reused_identity(self):
        with self.assertRaises(Refused):
            rotation.verify_rotation(self.envelope(), self.original)
        with patch.object(rotation, 'PUBLISHER_PIN', rotation.digest(self.new_key)):
            with self.assertRaises(Refused):
                rotation.candidate_for_key(self.original, self.new_key)
        with self.assertRaises(Refused):
            rotation.candidate_for_key(self.original, base64.b64decode(
                '4/+1LuuUX672KFUyjOh083T/C7DaR8DLurYWQVimfzA='))


if __name__ == '__main__':
    unittest.main()
