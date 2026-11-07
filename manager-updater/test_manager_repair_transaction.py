"""Synthetic offline commit and exact rollback; no owner data is opened."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app_bundle_backup import inventory
from creative_release import Refused, digest
from creative_transaction import atomic_write as actual_atomic_write
from manager_helper_inventory import HELPER_FILES
from manager_helper_release import stage_verified, verify_staged
from manager_repair_transaction import OfflineManagerRepair
from test_manager_repair_release import RepairReleaseTests, ROOT


class RepairTransactionTests(unittest.TestCase):
    def setUp(self):
        RepairReleaseTests.setUpClass()
        self.fixture = RepairReleaseTests('test_exact_signed_scope_and_nested_helper')
        self.fixture.setUp()
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'rap-brain'
        data = self.source / 'data'
        data.mkdir(parents=True)
        self.server = b'# synthetic server\n'
        self.fixture.payload['required_server_sha256'] = digest(self.server)
        (self.source / 'server.py').write_bytes(self.server)
        (self.source / 'creative_engine.py').write_bytes(b'# synthetic engine\n')
        (data / 'ollama_model.json').write_text('{"model":"synthetic"}')
        with sqlite3.connect(data / 'rapbrain.sqlite3') as conn:
            conn.execute('CREATE TABLE analyses (text TEXT)')
            conn.execute("INSERT INTO analyses VALUES ('never replace')")
        self.data_before = {p.name: p.read_bytes() for p in data.iterdir()}
        self.app = root / 'Manager.app'
        self.launcher = self.app / 'Contents/Resources/launch_manager.py'
        self.launcher.parent.mkdir(parents=True)
        (self.app / 'Contents/MacOS').mkdir(parents=True)
        with ZipFile(ROOT / 'manager-capability/capability-1.zip') as published:
            self.launcher.write_bytes(published.read('app/launch_manager.py'))
            old_archive = published.read('helper.zip')
        (self.launcher.parent / 'RapBrainManagerNative.swift').write_bytes(
            (ROOT.parent / 'beta14_inspection/RapBrainManagerNative.swift').read_bytes())
        (self.app / 'Contents/MacOS/RapBrainManagerNative').write_bytes(b'old native executable')
        self.app_before = inventory(self.app)
        self.state = root / 'state'
        self.state.mkdir(mode=0o700)
        now = self.fixture.helper_payload['issued_at']
        with ZipFile(io.BytesIO(old_archive)) as z:
            old_hashes = {name: digest(z.read('helper/' + name))
                          for name in HELPER_FILES}
        old_manifest = dict(self.fixture.helper_payload, sequence=1,
            files=old_hashes, archive_sha256=digest(old_archive),
            archive_bytes=len(old_archive))
        stage_verified(self.state, self.fixture.sign(old_manifest), old_archive,
                       pinned_key=self.fixture.pin, now=now)
        self.old_helper = {p.name: p.read_bytes()
                           for p in (self.state / 'helper').iterdir()}
        self.inspector = lambda *_: {'server_process_seen': False,
            'manager_process_seen': False, 'port_8765_listening': False}

    def transaction(self, signer=lambda *_a, **_k: True,
                    original_verifier=lambda *_a, **_k: True):
        return OfflineManagerRepair(self.source, self.launcher, self.state,
            inspector=self.inspector, pinned_key=self.fixture.pin,
            compiler=lambda *_: b'new synthetic native executable',
            original_verifier=original_verifier,
            restored_verifier=lambda *_a, **_k: True, signer=signer)

    def test_commit_preserves_synthetic_data_and_verified_backup(self):
        with patch('manager_repair_release.SERVER', digest(self.server)):
            result = self.transaction().install(
                self.fixture.sign(self.fixture.payload), self.fixture.archive)
        self.assertEqual(result['state'], 'committed')
        self.assertFalse(result['database_modified'])
        self.assertEqual({p.name: p.read_bytes() for p in
                          (self.source / 'data').iterdir()}, self.data_before)
        self.assertTrue((self.state / result['backup_id'] / 'backup.json').is_file())
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        verify_staged(self.state, pinned_key=self.fixture.pin)

    def test_signature_changes_native_binary_only_on_copy_before_switch(self):
        def macos_like_sign(app, *_args, **_kwargs):
            executable = app / 'Contents/MacOS/RapBrainManagerNative'
            executable.write_bytes(executable.read_bytes() + b'\nsynthetic signature')
            signature = app / 'Contents/_CodeSignature/CodeResources'
            signature.parent.mkdir()
            signature.write_bytes(b'synthetic signed resources')
            return True
        with patch('manager_repair_release.SERVER', digest(self.server)):
            result = self.transaction(signer=macos_like_sign).install(
                self.fixture.sign(self.fixture.payload), self.fixture.archive)
        self.assertEqual(result['state'], 'committed')
        self.assertEqual((self.app / 'Contents/MacOS/RapBrainManagerNative').read_bytes(),
                         b'new synthetic native executable\nsynthetic signature')
        self.assertEqual({p.name: p.read_bytes() for p in
                          (self.source / 'data').iterdir()}, self.data_before)

    def test_signing_failure_restores_app_helper_and_data(self):
        with patch('manager_repair_release.SERVER', digest(self.server)):
            result = self.transaction(signer=lambda *_a, **_k: False).install(
                self.fixture.sign(self.fixture.payload), self.fixture.archive)
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(inventory(self.app), self.app_before)
        self.assertEqual({p.name: p.read_bytes() for p in
                          (self.state / 'helper').iterdir()}, self.old_helper)
        self.assertEqual({p.name: p.read_bytes() for p in
                          (self.source / 'data').iterdir()}, self.data_before)
        self.assertFalse((self.state / 'maintenance.ticket').exists())

    def test_interrupted_helper_swap_resumes_original_attempt(self):
        rename = os.rename
        count = 0
        def interrupt_second_move(source, target):
            nonlocal count
            count += 1
            if count == 2:
                raise KeyboardInterrupt('synthetic power interruption')
            return rename(source, target)
        with patch('manager_repair_release.SERVER', digest(self.server)), \
                patch('manager_repair_transaction.os.rename',
                      side_effect=interrupt_second_move):
            with self.assertRaises(KeyboardInterrupt):
                self.transaction().install(
                    self.fixture.sign(self.fixture.payload), self.fixture.archive)
        self.assertTrue((self.state / 'maintenance.ticket').exists())
        self.assertEqual(json.loads((self.state / 'manager-repair.json').read_text())['phase'],
                         'switch_pending')
        with patch('manager_repair_release.SERVER', digest(self.server)):
            result = self.transaction().install()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(inventory(self.app), self.app_before)
        self.assertEqual({p.name: p.read_bytes() for p in
                          (self.state / 'helper').iterdir()}, self.old_helper)
        self.assertEqual({p.name: p.read_bytes() for p in
                          (self.source / 'data').iterdir()}, self.data_before)
        self.assertFalse((self.state / 'maintenance.ticket').exists())

    def test_unknown_change_keeps_backup_and_maintenance_marker(self):
        checks = 0
        def changed_binary(*_a, **_k):
            nonlocal checks
            checks += 1
            if checks == 3:
                (self.app / 'Contents/MacOS/RapBrainManagerNative').write_bytes(
                    b'unknown third-party change')
                return False
            return True
        with patch('manager_repair_release.SERVER', digest(self.server)):
            with self.assertRaisesRegex(Refused, 'manager_repair_unknown_live_code'):
                self.transaction(original_verifier=changed_binary).install(
                    self.fixture.sign(self.fixture.payload), self.fixture.archive)
        self.assertTrue((self.state / 'maintenance.ticket').exists())
        record = json.loads((self.state / 'manager-repair.json').read_text())
        self.assertTrue((self.state / record['id'] / 'app-backup.json').exists())
        self.assertEqual({p.name: p.read_bytes() for p in
                          (self.source / 'data').iterdir()}, self.data_before)

    def test_interrupted_app_file_switch_restores_exact_signed_original(self):
        def interrupt_after_launcher(path, raw, mode=0o600):
            result = actual_atomic_write(path, raw, mode)
            if Path(path) == self.launcher:
                raise KeyboardInterrupt('synthetic interrupted live switch')
            return result
        with patch('manager_repair_release.SERVER', digest(self.server)), \
                patch('manager_repair_transaction.atomic_write',
                      side_effect=interrupt_after_launcher):
            with self.assertRaises(KeyboardInterrupt):
                self.transaction().install(
                    self.fixture.sign(self.fixture.payload), self.fixture.archive)
        self.assertTrue((self.state / 'maintenance.ticket').exists())
        with patch('manager_repair_release.SERVER', digest(self.server)):
            result = self.transaction().install()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(inventory(self.app), self.app_before)
        self.assertEqual({p.name: p.read_bytes() for p in
                          (self.source / 'data').iterdir()}, self.data_before)
        self.assertFalse((self.state / 'maintenance.ticket').exists())


if __name__ == '__main__':
    unittest.main()
