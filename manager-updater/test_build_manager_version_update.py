"""One reviewed label update must pass signed copy and exact rollback."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
import io

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from build_manager_version_update import build, NAME
from creative_release import canonical, digest, Refused
from manager_update_release import verify_archive, verify_manifest
from manager_update_rehearsal import rehearse_on_copy
from manager_version_label_candidate import BASELINE_LAUNCHER_SHA256


CANDIDATE = Path(__file__).resolve().parent.parent / 'manager-capability' / 'capability-1.zip'


class VersionUpdateTests(unittest.TestCase):
    def test_deterministic_signed_copy_and_exact_rollback(self):
        archive = build(CANDIDATE)
        self.assertEqual(archive, build(CANDIDATE))
        with ZipFile(io.BytesIO(archive)) as zipped:
            self.assertEqual(zipped.namelist(), [NAME])
            payload = zipped.read(NAME)
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                               serialization.PublicFormat.Raw)
        server = b'# synthetic server, no production data\n'
        manifest = {'schema': 'rapbrain-manager-production-v1',
            'sequence': 1, 'issued_at': 100, 'expires_at': 200,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': {'macos_copy_install': 'passed',
                           'rollback': 'passed', 'runtime': 'passed'},
            'files': [{'path': NAME, 'baseline_sha256': BASELINE_LAUNCHER_SHA256,
                       'payload_sha256': digest(payload)}],
            'required_server_sha256': digest(server),
            'archive_url': ('https://raw.githubusercontent.com/albanherisson/'
                            'rap-brain-updates/main/manager-stable/update-1.zip'),
            'archive_sha256': digest(archive), 'archive_bytes': len(archive)}
        signed = canonical({'signed_payload': manifest,
            'signature_algorithm': 'Ed25519',
            'public_key_base64': base64.b64encode(public).decode(),
            'signature_base64': base64.b64encode(key.sign(canonical(manifest))).decode()})
        checked = verify_manifest(signed, pinned_key=digest(public), now=150)
        self.assertEqual(verify_archive(archive, checked), {NAME: payload})
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp).resolve()
            source = root / 'rap-brain'
            source.mkdir()
            (source / 'server.py').write_bytes(server)
            resources = root / 'Manager.app' / 'Contents' / 'Resources'
            resources.mkdir(parents=True)
            launcher = resources / 'launch_manager.py'
            with ZipFile(CANDIDATE) as original:
                baseline = original.read(NAME)
            launcher.write_bytes(baseline)
            state = root / 'state'
            result = rehearse_on_copy(source, launcher, state, signed, archive,
                                      pinned_key=digest(public), now=150)
            self.assertEqual(result['state'], 'copy_rehearsal_passed')
            self.assertEqual(launcher.read_bytes(), baseline)
            self.assertEqual((source / 'server.py').read_bytes(), server)
            self.assertFalse((source / 'data').exists())
        with self.assertRaises(Refused):
            verify_archive(archive + b'garbage', checked)


if __name__ == '__main__':
    unittest.main()
