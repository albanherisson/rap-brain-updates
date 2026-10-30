"""Release authentication and scope checks before any updater can write."""
import base64
import io
import json
import unittest
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from creative_release import Refused, canonical, digest
from manager_update_release import verify_archive, verify_manifest


class ManagerReleaseTest(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        self.pin = digest(self.public)
        self.payload = b'print("updated")\n'
        self.archive = self.zip_for('server.py', self.payload)
        self.manifest = {
            'schema': 'rapbrain-manager-production-v1', 'sequence': 2,
            'issued_at': 100, 'expires_at': 200,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': {'macos_copy_install': 'passed',
                           'rollback': 'passed', 'runtime': 'passed'},
            'files': [{'path': 'server.py', 'baseline_sha256': digest(b'old'),
                       'payload_sha256': digest(self.payload)}],
            'archive_url': ('https://raw.githubusercontent.com/albanherisson/'
                            'rap-brain-updates/main/manager-stable/update-2.zip'),
            'archive_sha256': digest(self.archive),
            'archive_bytes': len(self.archive),
        }

    @staticmethod
    def zip_for(path, payload):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr(path, payload)
        return stream.getvalue()

    def signed(self):
        value = {'signed_payload': self.manifest,
                 'signature_algorithm': 'Ed25519',
                 'signature_base64': base64.b64encode(
                     self.key.sign(canonical(self.manifest))).decode(),
                 'public_key_base64': base64.b64encode(self.public).decode()}
        return canonical(value)

    def verify(self):
        return verify_manifest(self.signed(), now=150, pinned_key=self.pin)

    def test_signed_source_update(self):
        self.assertEqual(verify_archive(self.archive, self.verify()),
                         {'server.py': self.payload})

    def test_data_and_unreviewed_files_refused_even_when_signed(self):
        for name in ('data/rapbrain.sqlite3', 'data/ollama_model.json',
                     'library/song.txt', '../server.py',
                     'app/Contents/MacOS/RapBrainManagerLegacy'):
            with self.subTest(name=name):
                self.manifest['files'][0]['path'] = name
                with self.assertRaises(Refused):
                    self.verify()

    def test_tamper_replay_and_mirror_refused(self):
        raw = json.loads(self.signed())
        raw['signed_payload']['sequence'] = 3
        with self.assertRaises((Refused, ValueError)):
            verify_manifest(canonical(raw), now=150, pinned_key=self.pin)
        with self.assertRaises(Refused):
            verify_manifest(self.signed(), now=150, minimum_sequence=2,
                            pinned_key=self.pin)
        self.manifest['archive_url'] = 'https://example.com/update.zip'
        with self.assertRaises(Refused):
            self.verify()

    def test_archive_extra_member_and_changed_bytes_refused(self):
        signed = self.verify()
        with self.assertRaises(Refused):
            verify_archive(self.archive + b'x', signed)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('server.py', self.payload)
            output.writestr('data/rapbrain.sqlite3', b'bad')
        signed['archive_sha256'] = digest(archive.getvalue())
        signed['archive_bytes'] = len(archive.getvalue())
        with self.assertRaises(Refused):
            verify_archive(archive.getvalue(), signed)


if __name__ == '__main__':
    unittest.main()
