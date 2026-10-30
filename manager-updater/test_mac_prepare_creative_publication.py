import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import io

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import creative_trust_rotation as rotation
from creative_release import canonical
import mac_prepare_creative_publication as publisher


class PublisherPreparationTests(unittest.TestCase):
    def test_creative_private_key_is_distinct_backed_up_and_not_in_public_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            (home / 'Downloads' / 'RapBrainManagerBackups').mkdir(parents=True)
            key = publisher.ensure_creative_key(home)
            backup = (home / 'Downloads' / 'RapBrainManagerBackups' /
                      'publisher-keys' / 'creative_ed25519.key')
            self.assertEqual(key.read_bytes(), backup.read_bytes())
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertEqual(publisher.ensure_creative_key(home), key)
            raw = publisher.public_zip({'manager-trust/creative-rotation-1.json': b'public',
                'creative-stable/engine-1.zip': b'payload'})
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                self.assertEqual(sorted(archive.namelist()),
                    ['creative-stable/engine-1.zip', 'manager-trust/creative-rotation-1.json'])
                self.assertNotIn(key.read_bytes(), raw)
            backup.write_bytes(b'x' * 32)
            with self.assertRaisesRegex(ValueError, 'backup_mismatch'):
                publisher.ensure_creative_key(home)

    def test_signed_rotation_payload_accepts_only_exact_installed_source(self):
        original = Path(rotation.__file__).with_name('creative_release.py').read_bytes()
        manager = Ed25519PrivateKey.generate()
        manager_public = manager.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        creative_public = Ed25519PrivateKey.generate().public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw)
        signed = publisher.rotation_payload(original, creative_public, 1_800_000_000)
        manifest = publisher.envelope(signed, manager_public,
                                      manager.sign(canonical(signed)))
        with patch.object(rotation, 'PUBLISHER_PIN', publisher.sha(manager_public)):
            payload, candidate = rotation.verify_rotation(manifest, original,
                                                         now=1_800_000_000)
        self.assertEqual(payload, signed)
        self.assertEqual(publisher.sha(candidate), signed['candidate_sha256'])
        with self.assertRaises(ValueError):
            publisher.rotation_payload(original + b'# different\n', creative_public,
                                       1_800_000_000)


if __name__ == '__main__':
    unittest.main()
