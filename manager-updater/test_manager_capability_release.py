"""An ephemeral publisher signs only disposable capability fixtures."""
import base64
import io
import time
import unittest
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from creative_release import Refused, canonical, digest
from manager_capability_release import (ARCHIVE, DASHBOARD_SHA256, EXPECTED,
    LAUNCHER_SHA256, SERVER_SHA256, verify_release)
from manager_helper_bundle import assemble as assemble_helper


class CapabilityReleaseTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.pin = digest(self.public)
        helper, hashes = assemble_helper()
        self.helper = helper
        now = int(time.time())
        self.helper_payload = {'schema': 'rapbrain-manager-helper-v1',
            'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True,
            'validation': {'macos_copy_install': 'passed', 'rollback': 'passed',
                           'runtime': 'passed'},
            'files': hashes, 'archive_sha256': digest(helper),
            'archive_bytes': len(helper)}
        self.files = {name: (helper if name == 'helper.zip' else
                            b'<html>candidate</html>' if name.endswith('.html') else
                            b'# synthetic code\n') for name in EXPECTED}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as zipout:
            for name in EXPECTED:
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100600 << 16)
                zipout.writestr(info, self.files[name])
        self.archive = stream.getvalue()
        self.payload = {'schema': 'rapbrain-manager-capability-v1',
            'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True,
            'validation': {'macos_copy_install': 'passed', 'rollback': 'passed',
                           'runtime': 'passed'}, 'data_migrations': [],
            'baseline_launcher_sha256': LAUNCHER_SHA256,
            'baseline_dashboard_sha256': DASHBOARD_SHA256,
            'required_server_sha256': SERVER_SHA256, 'archive_url': ARCHIVE,
            'archive_sha256': digest(self.archive),
            'archive_bytes': len(self.archive),
            'files': {name: digest(value) for name, value in self.files.items()},
            'helper_manifest_base64': base64.b64encode(
                self.sign(self.helper_payload)).decode()}

    def sign(self, value):
        return canonical({'signed_payload': value,
            'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(
                self.key.sign(canonical(value))).decode(),
            'public_key_base64': base64.b64encode(self.public).decode()})

    def test_exact_nested_signatures_and_candidate(self):
        signed, files, helper = verify_release(self.sign(self.payload),
                                               self.archive, pinned_key=self.pin)
        self.assertEqual(files, self.files)
        self.assertEqual(helper, self.sign(self.helper_payload))
        with self.assertRaises(Refused):
            verify_release(self.sign(self.payload), self.archive)

    def test_tamper_expiry_scope_and_changed_helper_are_refused(self):
        with self.assertRaises(Refused):
            verify_release(self.sign(self.payload).replace(b'"sequence":1',
                b'"sequence":2'), self.archive, pinned_key=self.pin)
        with self.assertRaises(Refused):
            verify_release(self.sign(self.payload), self.archive + b'!',
                           pinned_key=self.pin)
        with self.assertRaises(Refused):
            verify_release(self.sign(self.payload), self.archive,
                           pinned_key=self.pin, now=self.payload['expires_at'])
        changed = dict(self.payload, data_migrations=['sqlite'])
        with self.assertRaises(Refused):
            verify_release(self.sign(changed), self.archive, pinned_key=self.pin)
        changed = dict(self.payload, helper_manifest_base64=base64.b64encode(
            self.sign(dict(self.helper_payload, archive_sha256='0'*64))).decode())
        with self.assertRaises(Refused):
            verify_release(self.sign(changed), self.archive, pinned_key=self.pin)


if __name__ == '__main__':
    unittest.main()
