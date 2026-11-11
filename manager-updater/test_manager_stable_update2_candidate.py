import base64
from pathlib import Path
import time
import unittest
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from creative_release import canonical, digest
from manager_stable_update2_candidate import (BASELINE, MEMBER, archive_for)
from manager_update_release import verify_archive, verify_manifest


CAP = Path(__file__).resolve().parents[1] / 'manager-capability/capability-1.zip'
URL = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
       'main/manager-stable/update-2.zip')


class Update2CandidateTests(unittest.TestCase):
    def test_signed_channel_scopes_dashboard_only(self):
        with ZipFile(CAP) as published:
            baseline = published.read(MEMBER)
        archive, payload = archive_for(baseline)
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        now = int(time.time())
        signed = {'schema': 'rapbrain-manager-production-v1',
            'sequence': 2, 'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': {'macos_copy_install': 'passed', 'rollback': 'passed',
                           'runtime': 'passed'},
            'files': [{'path': MEMBER, 'baseline_sha256': BASELINE,
                       'payload_sha256': digest(payload)}],
            'required_server_sha256':
                'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27',
            'archive_url': URL, 'archive_sha256': digest(archive),
            'archive_bytes': len(archive)}
        envelope = canonical({'signed_payload': signed,
            'signature_algorithm': 'Ed25519',
            'public_key_base64': base64.b64encode(public).decode(),
            'signature_base64': base64.b64encode(
                key.sign(canonical(signed))).decode()})
        verified = verify_manifest(envelope, pinned_key=digest(public))
        self.assertEqual(verify_archive(archive, verified), {MEMBER: payload})
        self.assertIn(b'Mises \xc3\xa0 jour sign\xc3\xa9es disponibles', payload)
        with self.assertRaises(ValueError):
            archive_for(baseline + b' ')


if __name__ == '__main__':
    unittest.main()
