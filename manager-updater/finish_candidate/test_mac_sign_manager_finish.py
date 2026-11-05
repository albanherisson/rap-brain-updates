"""Check the publication format without loading any owner private key."""
import base64
import io
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import tempfile
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import mac_sign_manager_finish as publisher
from manager_update_release import verify_archive, verify_manifest


class PublicationTest(TestCase):
    def test_signed_dual_file_package_with_exact_baselines(self):
        workspace = Path(__file__).resolve().parents[2]
        candidate = (Path(__file__).resolve().parent /
                     'manager-update-3-candidate.zip').read_bytes()
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        with zipfile.ZipFile(workspace / 'upload/RapBrain_Manager_Postcommit_Publication.zip') as z:
            with zipfile.ZipFile(io.BytesIO(z.read('manager-postcommit/repair-3.zip'))) as r:
                launcher = r.read('app/launch_manager.py')
        with zipfile.ZipFile(workspace / 'upload/RapBrain_Manager_Repair_Publication(1).zip') as z:
            with zipfile.ZipFile(io.BytesIO(z.read('manager-stable/update-2.zip'))) as r:
                dashboard = r.read('app/dashboard_beta14.html')
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            app = (home / 'Downloads/RapBrainManager_App_Beta14/'
                   'Rap Brain Manager Beta 14.app/Contents/Resources')
            app.mkdir(parents=True)
            (app / 'launch_manager.py').write_bytes(launcher)
            (app / 'dashboard_beta14.html').write_bytes(dashboard)
            source = home / 'Downloads/rap-brain'
            source.mkdir()
            # Test content is synthetic; change published hashes only in memory.
            (source / 'server.py').write_text('synthetic server')
            (source / 'creative_engine.py').write_text('synthetic creative')
            with (patch.object(publisher, 'SERVER_SHA256',
                        publisher.digest((source / 'server.py').read_bytes())),
                  patch.object(publisher, 'CREATIVE_SHA256',
                        publisher.digest((source / 'creative_engine.py').read_bytes())),
                  patch.object(publisher.subprocess, 'run') as run,
                  patch.object(publisher, 'sign',
                        side_effect=lambda key, message: (public, private.sign(message)))):
                run.return_value.returncode = 0
                output = publisher.prepare(home, candidate, home / 'dummy-key',
                    now=1783360000, rehearsal=lambda *args: True)
            with zipfile.ZipFile(io.BytesIO(output)) as z:
                self.assertEqual(z.namelist(), ['manager-stable/manifest.json',
                                                  'manager-stable/update-3.zip'])
                envelope = z.read('manager-stable/manifest.json')
                archive = z.read('manager-stable/update-3.zip')
            manifest = verify_manifest(envelope, now=1783360000,
                                       pinned_key=publisher.digest(public))
            self.assertEqual(manifest['sequence'], 3)
            self.assertEqual(manifest['data_migrations'], [])
            self.assertEqual(set(verify_archive(archive, manifest)),
                             {'app/launch_manager.py', 'app/dashboard_beta14.html'})
