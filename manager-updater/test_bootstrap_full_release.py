"""Full signed bootstrap verification with disposable ephemeral test key."""
import base64
import io
import time
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from bootstrap_full_release import (FILES, RUNTIME_FILES, allowed_archive_url,
                                    verify_full_bootstrap, verify_full_manifest)
from bootstrap_download import download_bootstrap
from creative_release import Refused, canonical, digest


ROOT = Path(__file__).resolve().parent


class FullReleaseTests(unittest.TestCase):
    def setUp(self):
        self.before = {'server.py': b'original server',
                       'launch_manager.py': b'original launcher',
                       'dashboard_beta14.html': b'original dashboard'}
        self.after = {'server.py': b'guarded server',
                      'launch_manager.py': b'guarded launcher with UI bridge',
                      'dashboard_beta14.html': b'one-click dashboard'}
        self.after.update({name: (ROOT / name).read_bytes() for name in RUNTIME_FILES})
        self.key = Ed25519PrivateKey.generate()
        pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.pin = digest(pub)
        self.pub = base64.b64encode(pub).decode()
        self.make_release()

    def make_release(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for name in FILES:
                archive.writestr(name, self.after[name])
        self.archive = buffer.getvalue()
        now = int(time.time())
        self.payload = {'schema': 'rapbrain-guarded-bootstrap-v2',
            'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': {'isolated_rollback': 'passed', 'macos_runtime': 'passed'},
            'archive_url': 'https://albanherisson.github.io/rap-brain-updates/manager-bootstrap/guarded-1.zip',
            'archive_sha256': digest(self.archive), 'archive_bytes': len(self.archive),
            'runtime_sha256': {name: digest(self.after[name]) for name in RUNTIME_FILES}}
        for name, path in (('server', 'server.py'), ('launcher', 'launch_manager.py'),
                           ('dashboard', 'dashboard_beta14.html')):
            self.payload['baseline_' + name + '_sha256'] = digest(self.before[path])
            self.payload['candidate_' + name + '_sha256'] = digest(self.after[path])
        self.signed = canonical({'signed_payload': self.payload,
            'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(
                self.key.sign(canonical(self.payload))).decode(),
            'public_key_base64': self.pub})

    def verify(self, **overrides):
        with (patch('bootstrap_full_release.prepare_server',
                    return_value=self.after['server.py']),
              patch('bootstrap_full_release.prepare_launcher',
                    return_value=self.after['launch_manager.py']),
              patch('bootstrap_full_release.prepare_dashboard',
                    return_value=self.after['dashboard_beta14.html'])):
            return verify_full_bootstrap(self.signed, self.archive,
                self.before['server.py'], self.before['launch_manager.py'],
                self.before['dashboard_beta14.html'],
                pinned_key=overrides.get('pin', self.pin))

    def test_signed_complete_bundle(self):
        manifest, files = self.verify()
        self.assertEqual(manifest['sequence'], 1)
        self.assertEqual(set(files), set(FILES))
        self.assertEqual(verify_full_manifest(self.signed,
            *(self.before[name] for name in ('server.py', 'launch_manager.py',
                                             'dashboard_beta14.html')),
            pinned_key=self.pin)['archive_url'], self.payload['archive_url'])

    def test_distribution_url_stays_on_pinned_github_pages_directory(self):
        for url in ('https://evil.example/guarded-1.zip',
                    'https://albanherisson.github.io/rap-brain-updates/creative-stable/x.zip',
                    'https://albanherisson.github.io/rap-brain-updates/manager-bootstrap/x.zip?next=1'):
            with self.assertRaisesRegex(Refused, 'bootstrap_archive_url'):
                allowed_archive_url(url)

    def test_download_reads_archive_only_after_signed_manifest(self):
        requests = []
        def fetcher(url, cap):
            requests.append(url)
            return self.signed if len(requests) == 1 else self.archive
        with (patch('bootstrap_full_release.prepare_server',
                    return_value=self.after['server.py']),
              patch('bootstrap_full_release.prepare_launcher',
                    return_value=self.after['launch_manager.py']),
              patch('bootstrap_full_release.prepare_dashboard',
                    return_value=self.after['dashboard_beta14.html'])):
            raw, archive, _ = download_bootstrap(
                *(self.before[name] for name in ('server.py', 'launch_manager.py',
                                                 'dashboard_beta14.html')),
                pinned_key=self.pin, fetcher=fetcher)
        self.assertEqual((raw, archive), (self.signed, self.archive))
        self.assertEqual(len(requests), 2)

    def test_tampered_manifest_cannot_trigger_archive_download(self):
        self.signed = self.signed.replace(b'"sequence":1', b'"sequence":2')
        requests = []
        def fetcher(url, cap):
            requests.append(url)
            return self.signed
        with self.assertRaises(ValueError):
            download_bootstrap(*(self.before[name] for name in
                ('server.py', 'launch_manager.py', 'dashboard_beta14.html')),
                pinned_key=self.pin, fetcher=fetcher)
        self.assertEqual(len(requests), 1)

    def test_missing_runtime_member_refuses_even_when_archive_signed(self):
        self.after.pop('verify_ed25519.swift')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for name in FILES[:-1]:
                archive.writestr(name, self.after[name])
        self.archive = buffer.getvalue()
        self.payload['archive_bytes'] = len(self.archive)
        self.payload['archive_sha256'] = digest(self.archive)
        self.signed = canonical({'signed_payload': self.payload,
            'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(
                self.key.sign(canonical(self.payload))).decode(),
            'public_key_base64': self.pub})
        with self.assertRaisesRegex(Refused, 'bootstrap_archive_layout'):
            self.verify()

    def test_signature_and_baseline_refused(self):
        with self.assertRaisesRegex(Refused, 'bootstrap_publisher_mismatch'):
            self.verify(pin='0' * 64)
        changed = self.signed.replace(b'"sequence":1', b'"sequence":2')
        self.signed = changed
        with self.assertRaises(ValueError):
            self.verify()


if __name__ == '__main__':
    unittest.main()
