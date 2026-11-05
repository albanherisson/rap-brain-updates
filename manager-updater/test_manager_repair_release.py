"""A test publisher signs only disposable in-memory repair fixtures."""
import base64
import io
from pathlib import Path
import time
import unittest
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from build_manager_handoff_repair import build
from creative_release import Refused, canonical, digest
from manager_helper_inventory import HELPER_FILES
from manager_repair_release import (ARCHIVE, FILES, LAUNCHER, NATIVE_SOURCE,
    OLD_HELPER, SERVER, verify_release)


ROOT = Path(__file__).resolve().parents[1]


class RepairReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = build(ROOT / 'manager-capability' / 'capability-1.zip',
                          ROOT.parent / 'beta14_inspection' /
                          'RapBrainManagerNative.swift')

    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.pin = digest(self.public)
        now = int(time.time())
        with zipfile.ZipFile(io.BytesIO(self.files['helper.zip'])) as helper:
            hashes = {name: digest(helper.read('helper/' + name))
                      for name in HELPER_FILES}
        self.helper_payload = {'schema': 'rapbrain-manager-helper-v1',
            'sequence': 2, 'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True,
            'validation': {'macos_copy_install': 'passed', 'rollback': 'passed',
                           'runtime': 'passed'}, 'files': hashes,
            'archive_sha256': digest(self.files['helper.zip']),
            'archive_bytes': len(self.files['helper.zip'])}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            for name in FILES:
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100600 << 16)
                zipped.writestr(info, self.files[name])
        self.archive = stream.getvalue()
        self.payload = {'schema': 'rapbrain-manager-repair-v1', 'sequence': 2,
            'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': self.helper_payload['validation'],
            'baseline_launcher_sha256': LAUNCHER,
            'baseline_native_source_sha256': NATIVE_SOURCE,
            'baseline_helper_sha256': OLD_HELPER,
            'required_server_sha256': SERVER,
            'archive_url': ARCHIVE, 'archive_sha256': digest(self.archive),
            'archive_bytes': len(self.archive),
            'files': {k: digest(v) for k, v in self.files.items()},
            'helper_manifest_base64': base64.b64encode(
                self.sign(self.helper_payload)).decode()}

    def sign(self, payload):
        return canonical({'signed_payload': payload,
            'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(
                self.key.sign(canonical(payload))).decode(),
            'public_key_base64': base64.b64encode(self.public).decode()})

    def test_exact_signed_scope_and_nested_helper(self):
        signed, files, nested = verify_release(self.sign(self.payload),
            self.archive, pinned_key=self.pin)
        self.assertEqual(signed, self.payload)
        self.assertEqual(files, self.files)
        self.assertEqual(nested, self.sign(self.helper_payload))

    def test_refuses_data_tamper_expiry_and_wrong_publisher(self):
        with self.assertRaises(Refused):
            verify_release(self.sign(self.payload), self.archive)
        with self.assertRaises(Refused):
            verify_release(self.sign(self.payload), self.archive + b'!',
                           pinned_key=self.pin)
        with self.assertRaises(Refused):
            verify_release(self.sign(self.payload), self.archive,
                pinned_key=self.pin, now=self.payload['expires_at'])
        changed = dict(self.payload, data_migrations=['sqlite'])
        with self.assertRaises(Refused):
            verify_release(self.sign(changed), self.archive, pinned_key=self.pin)
        changed = dict(self.payload, baseline_helper_sha256='0'*64)
        with self.assertRaises(Refused):
            verify_release(self.sign(changed), self.archive, pinned_key=self.pin)
        changed = dict(self.payload, files=dict(self.payload['files'],
            **{'data/rapbrain.sqlite3': '0'*64}))
        with self.assertRaises(Refused):
            verify_release(self.sign(changed), self.archive, pinned_key=self.pin)


if __name__ == '__main__':
    unittest.main()
