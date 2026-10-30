import base64
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from bootstrap_full_release import PRIMARY, RUNTIME_FILES, verify_full_bootstrap
from creative_release import Refused, digest
from mac_sign_full_bootstrap import create_signed_release, transfer_bundle


class PublisherTransferTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.originals = {name: b'known original ' + name.encode() for name in PRIMARY}
        self.runtime = {name: (Path(__file__).parent / name).read_bytes()
                        for name in RUNTIME_FILES}
        self.updated = (b'guarded server', b'guarded launcher', b'guarded dashboard')

    def make_release(self):
        with (patch('bootstrap_release.PUBLISHER_PIN', digest(self.public)),
              patch('bootstrap_full_packager.prepare_server', return_value=self.updated[0]),
              patch('bootstrap_full_packager.prepare_launcher', return_value=self.updated[1]),
              patch('bootstrap_full_packager.prepare_dashboard', return_value=self.updated[2]),
              patch('bootstrap_full_release.prepare_server', return_value=self.updated[0]),
              patch('bootstrap_full_release.prepare_launcher', return_value=self.updated[1]),
              patch('bootstrap_full_release.prepare_dashboard', return_value=self.updated[2])):
            return create_signed_release(self.originals, self.runtime, self.public,
                                         self.key.sign, 1_800_000_000)

    def test_exact_two_file_transfer_and_independent_verification(self):
        manifest, archive, after = self.make_release()
        transfer = transfer_bundle(manifest, archive)
        with zipfile.ZipFile(BytesIO(transfer)) as bundle:
            self.assertEqual(bundle.namelist(), [
                'manager-bootstrap/guarded-1.zip',
                'manager-bootstrap/manifest.json'])
            self.assertEqual(bundle.read('manager-bootstrap/guarded-1.zip'), archive)
            self.assertEqual(bundle.read('manager-bootstrap/manifest.json'), manifest)
            self.assertEqual(len(bundle.namelist()), 2)
        with (patch('bootstrap_full_release.prepare_server', return_value=self.updated[0]),
              patch('bootstrap_full_release.prepare_launcher', return_value=self.updated[1]),
              patch('bootstrap_full_release.prepare_dashboard', return_value=self.updated[2])):
            payload, contents = verify_full_bootstrap(manifest, archive,
                *(self.originals[name] for name in PRIMARY),
                pinned_key=digest(self.public), now=1_800_000_000)
            with self.assertRaises(Refused):
                verify_full_bootstrap(manifest, archive + b'!',
                    *(self.originals[name] for name in PRIMARY),
                    pinned_key=digest(self.public), now=1_800_000_000)
        self.assertTrue(payload['production_install_authorized'])
        self.assertEqual(contents['server.py'], self.updated[0])
        self.assertEqual(after['server.py'], digest(self.updated[0]))
        self.assertEqual(base64.b64decode(json.loads(manifest)['public_key_base64']),
                         self.public)
        self.assertNotIn(b'private database', transfer)

    def test_wrong_signing_identity_refused_before_signing(self):
        with patch('bootstrap_release.PUBLISHER_PIN', digest(bytes(32))):
            with self.assertRaisesRegex(ValueError, 'publisher_identity_invalid'):
                create_signed_release(self.originals, self.runtime, self.public,
                                      self.key.sign, 1_800_000_000)


if __name__ == '__main__':
    unittest.main()
