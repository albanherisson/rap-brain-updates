from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
from io import BytesIO
import base64
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from bootstrap_full_packager import assemble
from bootstrap_full_release import FILES, PRIMARY, RUNTIME_FILES, verify_full_bootstrap
from creative_release import Refused, canonical, digest


class PackagerTests(unittest.TestCase):
    def test_deterministic_archive_matches_exact_verifier_inventory(self):
        original = {name: b'fixture original ' + name.encode() for name in PRIMARY}
        runtime = {name: (Path(__file__).parent / name).read_bytes()
                   for name in RUNTIME_FILES}
        with (patch('bootstrap_full_packager.prepare_server', return_value=b'new server'),
              patch('bootstrap_full_packager.prepare_launcher', return_value=b'new launcher'),
              patch('bootstrap_full_packager.prepare_dashboard', return_value=b'new dashboard')):
            first, hashes, before = assemble(original, runtime)
            second, _, _ = assemble(original, runtime)
        self.assertEqual(first, second)
        with zipfile.ZipFile(BytesIO(first)) as archive:
            self.assertEqual(tuple(archive.namelist()), FILES)
            self.assertEqual(digest(archive.read('server.py')), hashes['server.py'])
        self.assertEqual(before['server.py'], digest(original['server.py']))
        self.assertNotIn(b'fixture private database', first)

    def test_missing_runtime_refused_before_archive(self):
        originals = {name: b'fixture' for name in PRIMARY}
        with self.assertRaises(Refused):
            assemble(originals, {})

    def test_assembled_archive_passes_independent_signed_verifier(self):
        originals = {name: b'fixture original ' + name.encode() for name in PRIMARY}
        runtime = {name: (Path(__file__).parent / name).read_bytes()
                   for name in RUNTIME_FILES}
        updates = (b'guarded server', b'guarded launcher', b'guarded dashboard')
        patches = (patch('bootstrap_full_packager.prepare_server', return_value=updates[0]),
                   patch('bootstrap_full_packager.prepare_launcher', return_value=updates[1]),
                   patch('bootstrap_full_packager.prepare_dashboard', return_value=updates[2]))
        with patches[0], patches[1], patches[2]:
            archive, after, before = assemble(originals, runtime)
        now = int(time.time())
        manifest = {'schema': 'rapbrain-guarded-bootstrap-v2', 'sequence': 1,
            'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': {'isolated_rollback': 'passed', 'macos_runtime': 'passed'},
            'archive_url': 'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/main/manager-bootstrap/guarded-1.zip',
            'archive_sha256': digest(archive), 'archive_bytes': len(archive),
            'runtime_sha256': {name: after[name] for name in RUNTIME_FILES}}
        for field, name in zip(('server', 'launcher', 'dashboard'), PRIMARY):
            manifest['baseline_' + field + '_sha256'] = before[name]
            manifest['candidate_' + field + '_sha256'] = after[name]
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        signed = canonical({'signed_payload': manifest, 'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(key.sign(canonical(manifest))).decode(),
            'public_key_base64': base64.b64encode(public).decode()})
        with (patch('bootstrap_full_release.prepare_server', return_value=updates[0]),
              patch('bootstrap_full_release.prepare_launcher', return_value=updates[1]),
              patch('bootstrap_full_release.prepare_dashboard', return_value=updates[2])):
            verified, contents = verify_full_bootstrap(signed, archive,
                *(originals[name] for name in PRIMARY), pinned_key=digest(public))
        self.assertEqual(verified, manifest)
        self.assertEqual(contents['server.py'], updates[0])
