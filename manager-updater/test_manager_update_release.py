"""Release authentication and scope checks before any updater can write."""
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from creative_release import Refused, canonical, digest
from manager_update_release import (CHANNEL, download_release, verify_archive,
                                    verify_baseline, verify_manifest)


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

    def test_signature_checked_before_payload_download(self):
        calls = []
        def downloader(url, limit):
            calls.append(url)
            return self.signed() if url == CHANNEL else self.archive
        with self.assertRaises(Refused):
            download_release(downloader=downloader)
        self.assertEqual(calls, [CHANNEL])
        calls.clear()
        # Real release timestamps are checked too; this old fixture cannot
        # be installed by merely supplying a valid signature.
        self.manifest['issued_at'] = 1_000_000_000
        self.manifest['expires_at'] = 1_000_000_100
        with patch('manager_update_release.time.time', return_value=1_000_000_050):
            raw, archive, files = download_release(
                downloader=downloader, pinned_key=self.pin)
        self.assertEqual(calls, [CHANNEL, self.manifest['archive_url']])
        self.assertEqual(files, {'server.py': self.payload})

    def test_baseline_reads_only_selected_code(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'rap-brain'
            resources = Path(root) / 'resources'
            source.mkdir()
            resources.mkdir()
            (source / 'server.py').write_bytes(b'old')
            (source / 'data').mkdir()
            (source / 'data' / 'rapbrain.sqlite3').write_bytes(b'untouched')
            manifest = self.verify()
            self.assertEqual(verify_baseline(manifest, source, resources),
                             {'server.py': source / 'server.py'})
            (source / 'server.py').write_bytes(b'changed')
            with self.assertRaises(Refused):
                verify_baseline(manifest, source, resources)


if __name__ == '__main__':
    unittest.main()
