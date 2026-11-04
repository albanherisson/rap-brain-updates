"""Signed external helper refuses changed code, extra files and stale consent."""
import base64
import io
from pathlib import Path
import tempfile
import time
import unittest
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from creative_release import Refused, canonical, digest
from manager_helper_bundle import assemble
from manager_helper_release import stage_verified, verify_archive, verify_manifest


class HelperReleaseTests(unittest.TestCase):
    def setUp(self):
        self.archive, files = assemble()
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.pin = digest(self.public)
        now = int(time.time())
        self.payload = {'schema': 'rapbrain-manager-helper-v1', 'sequence': 1,
            'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True,
            'validation': {'macos_copy_install': 'passed',
                           'rollback': 'passed', 'runtime': 'passed'},
            'files': files, 'archive_sha256': digest(self.archive),
            'archive_bytes': len(self.archive)}

    def signed(self, payload):
        return canonical({'signed_payload': payload,
            'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(
                self.key.sign(canonical(payload))).decode(),
            'public_key_base64': base64.b64encode(self.public).decode()})

    def test_exact_signature_and_bundle(self):
        manifest = verify_manifest(self.signed(self.payload), pinned_key=self.pin)
        members = verify_archive(self.archive, manifest)
        self.assertEqual(set(members), set(self.payload['files']))
        with self.assertRaises(Refused):
            verify_manifest(self.signed(self.payload))  # Production key is distinct.

    def test_changed_archive_and_extra_member_refused(self):
        manifest = verify_manifest(self.signed(self.payload), pinned_key=self.pin)
        with self.assertRaises(Refused):
            verify_archive(self.archive + b'\0', manifest)
        stream = io.BytesIO(self.archive)
        with zipfile.ZipFile(stream, 'a') as archive:
            archive.writestr('helper/extra.py', b'pass\n')
        changed = stream.getvalue()
        payload = dict(self.payload, archive_sha256=digest(changed),
                       archive_bytes=len(changed))
        with self.assertRaises(Refused):
            verify_archive(changed, verify_manifest(self.signed(payload),
                                                   pinned_key=self.pin))

    def test_signature_expiry_and_validation_claim_enforced(self):
        altered = dict(self.payload, sequence=2)
        with self.assertRaises(Refused):
            verify_manifest(self.signed(self.payload).replace(b'"sequence":1',
                b'"sequence":2'), pinned_key=self.pin)
        with self.assertRaises(Refused):
            verify_manifest(self.signed(altered), pinned_key=self.pin,
                            now=altered['expires_at'])
        altered['validation'] = {'macos_copy_install': 'passed',
                                 'rollback': 'passed', 'runtime': 'untested'}
        with self.assertRaises(Refused):
            verify_manifest(self.signed(altered), pinned_key=self.pin)

    def test_staging_is_private_complete_and_refuses_second_attempt(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            state = Path(temp) / 'state'
            state.mkdir(mode=0o700)
            signed = self.signed(self.payload)
            result = stage_verified(state, signed, self.archive,
                                    pinned_key=self.pin)
            self.assertEqual(result['files'], len(self.payload['files']))
            helper = state / 'helper'
            self.assertEqual(helper.stat().st_mode & 0o777, 0o700)
            self.assertEqual((helper / 'manager_update_helper.py').stat().st_mode
                             & 0o777, 0o600)
            self.assertEqual(digest((helper / 'manager_update_helper.py').read_bytes()),
                             self.payload['files']['manager_update_helper.py'])
            with self.assertRaises(Refused):
                stage_verified(state, signed, self.archive, pinned_key=self.pin)

    def test_bad_signature_never_creates_helper_or_lock(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            state = Path(temp) / 'state'
            state.mkdir(mode=0o700)
            with self.assertRaises(Refused):
                stage_verified(state, self.signed(self.payload).replace(
                    b'"sequence":1', b'"sequence":2'),
                               self.archive, pinned_key=self.pin)
            self.assertEqual(list(state.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
