import base64
from pathlib import Path
import plistlib
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import creative_trust_rotation as rotation
import creative_trust_transaction as transaction_module
from creative_release import canonical
from creative_trust_transaction import OfflineTrustRotation


class RotationTransactionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.source = self.root / 'rap-brain'
        data = self.source / 'data'
        data.mkdir(parents=True)
        (self.source / 'server.py').write_bytes(b'guarded test server')
        (self.source / 'creative_engine.py').write_bytes(b'# unchanged engine\n')
        (data / 'ollama_model.json').write_text('{"model":"fixture"}')
        with sqlite3.connect(data / 'rapbrain.sqlite3') as db:
            db.execute('CREATE TABLE fixture (value TEXT)')
            db.execute('INSERT INTO fixture VALUES (?)', ('retain',))
        (data / 'lyrics.txt').write_text('retain')
        self.data_before = {p.name: p.read_bytes() for p in data.iterdir()}
        self.app = self.root / 'Rap Brain Manager Beta 14.app'
        resources = self.app / 'Contents' / 'Resources'
        resources.mkdir(parents=True)
        self.launcher = resources / 'launch_manager.py'
        self.launcher.write_bytes(b'# fixture\n')
        self.target = resources / 'creative_release.py'
        self.original = Path(rotation.__file__).with_name('creative_release.py').read_bytes()
        self.target.write_bytes(self.original)
        self.state = self.root / 'private-state'
        self.state.mkdir(mode=0o700)
        self.publisher = Ed25519PrivateKey.generate()
        pub = self.publisher.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.new_pub = Ed25519PrivateKey.generate().public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw)
        candidate = rotation.candidate_for_key(self.original, self.new_pub)
        now = int(time.time())
        signed = {'schema': 'rapbrain-creative-trust-rotation-v1', 'sequence': 1,
                  'issued_at': now-1, 'expires_at': now+3600,
                  'production_install_authorized': True,
                  'target': 'creative_release.py', 'data_migrations': [],
                  'baseline_sha256': rotation.digest(self.original),
                  'candidate_sha256': rotation.digest(candidate),
                  'new_public_key_base64': base64.b64encode(self.new_pub).decode(),
                  'new_public_key_sha256': rotation.digest(self.new_pub)}
        self.manifest = canonical({'signed_payload': signed,
            'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(
                self.publisher.sign(canonical(signed))).decode(),
            'public_key_base64': base64.b64encode(pub).decode()})
        self.publisher_pin = rotation.digest(pub)
        self.candidate = candidate

    @staticmethod
    def idle(*_):
        return {'server_process_seen': False, 'manager_process_seen': False,
                'port_8765_listening': False}

    def transaction(self, signer=None):
        return OfflineTrustRotation(self.source, self.launcher, self.state,
            inspector=self.idle, signer=signer or (lambda *a, **k: True),
            restored_verifier=lambda *a, **k: True,
            candidate_verifier=lambda *a, **k: True)

    def unchanged_data(self):
        self.assertEqual({p.name: p.read_bytes() for p in (self.source / 'data').iterdir()},
                         self.data_before)

    def run_with_fixtures(self, transaction):
        with patch.object(rotation, 'PUBLISHER_PIN', self.publisher_pin), \
                patch.object(transaction_module, 'SERVER_SHA256',
                    rotation.digest((self.source / 'server.py').read_bytes())):
            return transaction.install(self.manifest)

    def test_commit_only_rotates_one_app_file_and_backs_up_data(self):
        result = self.run_with_fixtures(self.transaction())
        self.assertEqual(result['state'], 'committed', result)
        self.assertEqual(self.target.read_bytes(), self.candidate)
        self.assertEqual(self.launcher.read_bytes(), b'# fixture\n')
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        backup = self.state / result['backup_id']
        self.assertEqual((backup / 'ollama_model.json').read_bytes(),
                         self.data_before['ollama_model.json'])
        with sqlite3.connect(backup / 'rapbrain.sqlite3') as db:
            self.assertEqual(db.execute('SELECT value FROM fixture').fetchone(), ('retain',))
        self.unchanged_data()

    def test_failed_signature_restores_original_app_and_data(self):
        result = self.run_with_fixtures(self.transaction(signer=lambda *a, **k: False))
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.unchanged_data()

    def test_crash_after_replacement_recovers_from_saved_app(self):
        def crash(*_args, **_kwargs):
            raise KeyboardInterrupt('disposable power loss')
        with self.assertRaises(KeyboardInterrupt):
            self.run_with_fixtures(self.transaction(signer=crash))
        self.assertTrue((self.state / 'maintenance.ticket').exists())
        result = self.run_with_fixtures(self.transaction())
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.unchanged_data()

    def test_crash_after_commit_finishes_without_replacing_again(self):
        with patch.object(OfflineTrustRotation, '_finish', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_with_fixtures(self.transaction())
        self.assertEqual(self.target.read_bytes(), self.candidate)
        self.assertTrue((self.state / 'maintenance.ticket').exists())
        result = self.run_with_fixtures(self.transaction())
        self.assertEqual(result['state'], 'committed', result)
        self.assertTrue(result['recovered'])
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.unchanged_data()

    def test_unexpected_app_change_rolls_back(self):
        def signer(app, *_args, **_kwargs):
            (app / 'Contents' / 'Resources' / 'launch_manager.py').write_bytes(b'tampered')
            return True
        result = self.run_with_fixtures(self.transaction(signer=signer))
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(self.launcher.read_bytes(), b'# fixture\n')
        self.assertEqual(self.target.read_bytes(), self.original)
        self.unchanged_data()

    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS codesign')
    def test_real_macos_app_sign_and_exact_restore_on_copy(self):
        (self.app / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'org.rapbrain.disposable-trust-rotation',
            'CFBundleExecutable': 'DisposableRapBrain',
            'CFBundleName': 'Disposable Rap Brain',
            'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1'}))
        native = self.app / 'Contents' / 'MacOS' / 'DisposableRapBrain'
        native.parent.mkdir()
        native.write_bytes(Path('/bin/echo').read_bytes())
        native.chmod(0o755)
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-',
                        str(self.app)], check=True, capture_output=True)
        from app_bundle_backup import inventory
        before = inventory(self.app)
        tx = OfflineTrustRotation(self.source, self.launcher, self.state,
                                  inspector=self.idle)
        result = self.run_with_fixtures(tx)
        self.assertEqual(result['state'], 'committed', result)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                        str(self.app)], check=True, capture_output=True)
        folder = self.state / result['backup_id']
        from app_bundle_backup import restore_app_backup
        self.assertTrue(restore_app_backup(self.app, folder))
        self.assertEqual(inventory(self.app), before)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                        str(self.app)], check=True, capture_output=True)
        self.unchanged_data()


if __name__ == '__main__':
    unittest.main()
