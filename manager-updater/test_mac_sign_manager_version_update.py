"""Owner signing refuses changed active code and keeps SQLite untouched."""
import hashlib
import io
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

import mac_sign_manager_version_update as publisher
from manager_update_release import verify_archive, verify_manifest


ARCHIVE = Path(__file__).resolve().parent.parent / 'manager-stable' / 'update-1.zip'


class OwnerSigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.resources = (self.home / 'Downloads' / 'RapBrainManager_App_Beta14' /
            'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources')
        self.resources.mkdir(parents=True)
        self.source = self.home / 'Downloads' / 'rap-brain'
        self.source.mkdir()
        self.key = self.home / 'publisher.key'
        seed = bytes(range(32))
        self.key.write_bytes(seed)
        self.key.chmod(0o600)
        public = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.pin = hashlib.sha256(public).hexdigest()
        with ZipFile(Path(__file__).resolve().parent.parent /
                     'manager-capability' / 'capability-1.zip') as original:
            self.resources.joinpath('launch_manager.py').write_bytes(
                original.read('app/launch_manager.py'))
            self.resources.joinpath('dashboard_beta14.html').write_bytes(
                original.read('app/dashboard_beta14.html'))
        # The hashes stand in for the production server and P8 engine; only
        # the immutable signed bytes are used in the real publisher.
        self.source.joinpath('server.py').write_bytes(b'synthetic server')
        self.source.joinpath('creative_engine.py').write_bytes(b'synthetic engine')
        self.backups = self.home / 'Downloads' / 'RapBrainManagerBackups'
        self.backups.mkdir()
        self.db = self.source / 'data' / 'rapbrain.sqlite3'
        self.db.parent.mkdir()
        self.db.write_bytes(b'do-not-read-or-change')

    def test_signs_exact_release_without_opening_data(self):
        before = self.db.read_bytes()
        with patch.object(publisher, 'MANAGER_PIN', self.pin), \
             patch.object(publisher, 'SERVER_SHA256', publisher.digest(b'synthetic server')), \
             patch.object(publisher, 'CREATIVE_SHA256', publisher.digest(b'synthetic engine')), \
             patch.object(publisher.subprocess, 'run') as codesign:
            codesign.return_value.returncode = 0
            rehearsed = []
            result = publisher.prepare(self.home, ARCHIVE.read_bytes(), self.key,
                now=1_793_820_000,
                rehearsal=lambda app, code, state: rehearsed.append(
                    (app, publisher.digest(code), state)) or True)
        codesign.assert_called_once()
        self.assertEqual(rehearsed[0][1], publisher.PAYLOAD_SHA256)
        self.assertEqual(rehearsed[0][2], self.backups)
        with ZipFile(io.BytesIO(result)) as zipped:
            self.assertEqual(zipped.namelist(),
                ['manager-stable/manifest.json', 'manager-stable/update-1.zip'])
            signed = zipped.read('manager-stable/manifest.json')
            archive = zipped.read('manager-stable/update-1.zip')
        checked = verify_manifest(signed, pinned_key=self.pin, now=1_793_820_000)
        self.assertEqual(list(verify_archive(archive, checked)), ['app/launch_manager.py'])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertNotIn(bytes(range(32)), result)

    def test_changed_baseline_refuses_before_signing(self):
        self.resources.joinpath('launch_manager.py').write_bytes(b'modified')
        with patch.object(publisher, 'MANAGER_PIN', self.pin), \
             patch.object(publisher, 'SERVER_SHA256', publisher.digest(b'synthetic server')), \
             patch.object(publisher, 'CREATIVE_SHA256', publisher.digest(b'synthetic engine')), \
             patch.object(publisher.subprocess, 'run') as codesign:
            with self.assertRaisesRegex(ValueError, 'publisher_active_baseline_changed'):
                publisher.prepare(self.home, ARCHIVE.read_bytes(), self.key,
                                  now=1_793_820_000)
        codesign.assert_not_called()

    def test_copy_signing_and_exact_rollback_do_not_change_active_app(self):
        app = self.resources.parents[1]
        before = publisher.app_inventory(app)
        with ZipFile(ARCHIVE) as zipped:
            payload = zipped.read(publisher.MEMBER)
        commands = []
        def run(args, **_kwargs):
            commands.append(args)
            if args[0] == '/usr/bin/ditto':
                shutil.copytree(args[1], args[2], copy_function=shutil.copy2)
            return SimpleNamespace(returncode=0)
        self.assertTrue(publisher.rehearse_on_copy(app, payload, self.backups,
                                                    runner=run))
        self.assertEqual(publisher.app_inventory(app), before)
        self.assertEqual([c[0] for c in commands].count('/usr/bin/ditto'), 3)
        self.assertEqual([c[0] for c in commands].count('/usr/bin/codesign'), 5)
        self.assertEqual(list(self.backups.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
