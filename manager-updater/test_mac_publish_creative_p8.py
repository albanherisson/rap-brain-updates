import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (Encoding, PrivateFormat,
    PublicFormat, NoEncryption)

from creative_release import digest, verify_archive, verify_manifest
from mac_publish_creative_p8 import (BASELINE, PAYLOAD, SERVER, canonical,
    candidate_keys, key_file, make_envelope, one_file_archive, production_payload,
    sign_existing_identity, sign_with_key)


P8 = Path(__file__).resolve().parents[2] / 'upload' / 'RapBrain_CreativeEngine_P8_Signed_Candidate.zip'


class PublisherTests(unittest.TestCase):
    def test_real_p8_code_makes_exact_production_archive(self):
        if not P8.is_file():
            self.skipTest('owner P8 attachment unavailable in checkout')
        with zipfile.ZipFile(P8) as package:
            code = package.read('creative_engine.py')
        archive = one_file_archive(code)
        payload = production_payload(archive, now=1793352000)
        self.assertEqual((payload['baseline_sha256'], payload['required_server_sha256'],
                          payload['payload_sha256']), (BASELINE, SERVER, PAYLOAD))
        self.assertEqual(payload['archive_sha256'], digest(archive))
        self.assertEqual(verify_archive(archive, payload), code)
        self.assertEqual(zipfile.ZipFile(io.BytesIO(archive)).namelist(),
                         ['creative_engine.py'])

    def test_only_matching_private_identity_can_sign_production(self):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        # The production default rejects a test publisher key.
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            support = home / 'Library' / 'Application Support' / 'RapBrainManager'
            support.mkdir(parents=True)
            path = support / 'creative_ed25519.key'
            path.write_bytes(key.private_bytes(Encoding.Raw, PrivateFormat.Raw,
                                              NoEncryption()))
            path.chmod(0o600)
            self.assertTrue(key_file(path))
            self.assertIn(path, candidate_keys(home))
            self.assertEqual(sign_with_key(path, b'public manifest', home)[0], public)
            with self.assertRaisesRegex(ValueError, 'p8_publisher_key_not_found'):
                sign_existing_identity(b'public manifest', home, home=home)
            path.chmod(0o644)
            self.assertFalse(key_file(path))

    def test_envelope_conforms_to_installed_release_gate(self):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        archive = b'fixture'
        payload = production_payload(archive, now=1793352000)
        with patch('mac_publish_creative_p8.PUBLIC', public):
            raw = make_envelope(payload, key.sign(canonical(payload)))
        self.assertEqual(json.loads(raw)['signed_payload']['data_migrations'], [])
        self.assertEqual(verify_manifest(raw, pinned_key=digest(public),
                                         now=1793352000), payload)

    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS CryptoKit')
    def test_swift_can_sign_without_python_crypto(self):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = home / 'creative_ed25519.key'
            path.write_bytes(key.private_bytes(Encoding.Raw, PrivateFormat.Raw,
                                              NoEncryption()))
            path.chmod(0o600)
            with patch.dict(sys.modules, {
                'cryptography.hazmat.primitives': None}):
                signed = sign_with_key(path, b'public manifest', home)
            self.assertEqual(signed[0], public)
            key.public_key().verify(signed[1], b'public manifest')


if __name__ == '__main__':
    unittest.main()
