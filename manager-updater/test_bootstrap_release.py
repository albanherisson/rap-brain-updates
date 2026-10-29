import base64
import io
import json
import time
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from bootstrap_release import verify_bootstrap
from creative_release import Refused, canonical, digest


class BootstrapReleaseTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.before = {'server.py': b'old server', 'launch_manager.py': b'old launcher'}
        self.after = {'server.py': b'guarded server', 'launch_manager.py': b'guarded launcher'}
        self.archive = self.zip(self.after)
        now = int(time.time())
        self.payload = {'schema': 'rapbrain-guarded-bootstrap-v1', 'sequence': 1,
                        'issued_at': now - 1, 'expires_at': now + 3600,
                        'production_install_authorized': True,
                        'baseline_server_sha256': digest(self.before['server.py']),
                        'baseline_launcher_sha256': digest(self.before['launch_manager.py']),
                        'candidate_server_sha256': digest(self.after['server.py']),
                        'candidate_launcher_sha256': digest(self.after['launch_manager.py']),
                        'archive_sha256': digest(self.archive), 'archive_bytes': len(self.archive),
                        'data_migrations': [],
                        'validation': {'isolated_rollback': 'passed', 'macos_runtime': 'passed'}}

    def zip(self, contents):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
        return buffer.getvalue()

    def signed(self):
        return canonical({'signed_payload': self.payload,
                          'signature_algorithm': 'Ed25519',
                          'signature_base64': base64.b64encode(
                              self.key.sign(canonical(self.payload))).decode(),
                          'public_key_base64': base64.b64encode(self.pub).decode()})

    def verify(self, signed=None, archive=None, server=None):
        with (patch('bootstrap_release.prepare_server', return_value=self.after['server.py']),
              patch('bootstrap_release.prepare_launcher',
                    return_value=self.after['launch_manager.py'])):
            return verify_bootstrap(
                self.signed() if signed is None else signed,
                self.archive if archive is None else archive,
                self.before['server.py'] if server is None else server,
                self.before['launch_manager.py'], pinned_key=digest(self.pub))

    def test_signed_two_file_candidate_and_tampering(self):
        manifest, files = self.verify()
        self.assertEqual(manifest['sequence'], 1)
        self.assertEqual(files, self.after)
        with self.assertRaisesRegex(Refused, 'bootstrap_baseline_changed'):
            self.verify(server=b'changed live server')
        with self.assertRaisesRegex(Refused, 'bootstrap_archive_integrity'):
            self.verify(archive=self.archive + b'altered')
        changed = self.signed().replace(b'"sequence":1', b'"sequence":2')
        with self.assertRaises(Refused):
            self.verify(signed=changed)

    def test_unexpected_payload_and_missing_macos_validation_refuse(self):
        altered = dict(self.after, **{'launch_manager.py': b'unexpected code'})
        bad_zip = self.zip(altered)
        self.payload['archive_sha256'] = digest(bad_zip)
        self.payload['archive_bytes'] = len(bad_zip)
        self.payload['candidate_launcher_sha256'] = digest(altered['launch_manager.py'])
        with self.assertRaisesRegex(Refused, 'bootstrap_unexpected_code'):
            self.verify(archive=bad_zip)
        self.payload['validation']['macos_runtime'] = 'not_run'
        with self.assertRaisesRegex(Refused, 'bootstrap_not_authorized'):
            self.verify(archive=bad_zip)

    def test_archive_extra_member_refused(self):
        bad = self.zip(dict(self.after, **{'data/rapbrain.sqlite3': b'evil'}))
        self.payload['archive_sha256'] = digest(bad)
        self.payload['archive_bytes'] = len(bad)
        with self.assertRaisesRegex(Refused, 'bootstrap_archive_layout'):
            self.verify(archive=bad)


if __name__ == '__main__':
    unittest.main()
