"""Disposable signed capability commit, rollback and interrupted recovery."""
import json
from pathlib import Path
import plistlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from creative_release import digest
from manager_capability_transaction import OfflineManagerCapability
import manager_capability_release as release
from test_manager_capability_release import CapabilityReleaseTests


class CapabilityTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.source = root / 'rap-brain'
        data = self.source / 'data'
        data.mkdir(parents=True)
        (self.source / 'server.py').write_bytes(b'# guarded fixture\n')
        (self.source / 'creative_engine.py').write_bytes(b'# original engine\n')
        (data / 'ollama_model.json').write_text('{"model":"synthetic"}')
        with sqlite3.connect(data / 'rapbrain.sqlite3') as db:
            db.execute('CREATE TABLE analyses (id INTEGER PRIMARY KEY, text TEXT)')
            db.execute("INSERT INTO analyses(text) VALUES ('keep')")
        self.data_before = {p.name: p.read_bytes() for p in data.iterdir()}
        self.app = root / 'Rap Brain Manager Beta 14.app'
        resources = self.app / 'Contents' / 'Resources'
        resources.mkdir(parents=True)
        (self.app / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleExecutable': 'RapBrainManagerLegacy',
            'CFBundleIdentifier': 'org.rapbrain.disposable-capability',
            'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1'}))
        native = self.app / 'Contents' / 'MacOS' / 'RapBrainManagerLegacy'
        native.parent.mkdir()
        native.write_bytes(b'#!/bin/sh\nexit 0\n')
        native.chmod(0o755)
        self.launcher = resources / 'launch_manager.py'
        self.dashboard = resources / 'dashboard_beta14.html'
        self.launcher.write_bytes(b'# old launcher\n')
        self.dashboard.write_bytes(b'<html>old</html>')
        self.state = root / 'secure-update'
        self.state.mkdir(mode=0o700)
        self.signed_fixture = CapabilityReleaseTests()
        self.signed_fixture.setUp()
        self.signed_fixture.payload.update(
            baseline_launcher_sha256=digest(self.launcher.read_bytes()),
            baseline_dashboard_sha256=digest(self.dashboard.read_bytes()),
            required_server_sha256=digest((self.source / 'server.py').read_bytes()))
        self.raw = self.signed_fixture.sign(self.signed_fixture.payload)
        self.archive = self.signed_fixture.archive
        self.patches = [
            patch.object(release, 'LAUNCHER_SHA256', digest(self.launcher.read_bytes())),
            patch.object(release, 'DASHBOARD_SHA256', digest(self.dashboard.read_bytes())),
            patch.object(release, 'SERVER_SHA256', digest((self.source / 'server.py').read_bytes()))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.offline = lambda *_: {'server_process_seen': False,
                                   'manager_process_seen': False,
                                   'port_8765_listening': False}

    def transaction(self, signer=lambda *_args, **_kwargs: True):
        return OfflineManagerCapability(self.source, self.launcher, self.state,
            inspector=self.offline, signer=signer,
            original_verifier=lambda *_args, **_kwargs: True,
            restored_verifier=lambda *_args, **_kwargs: True,
            pinned_key=self.signed_fixture.pin)

    def assert_data(self):
        data = self.source / 'data'
        self.assertEqual(self.data_before,
                         {p.name: p.read_bytes() for p in data.iterdir()})

    def test_commit_and_idempotent_reopen(self):
        result = self.transaction().install(self.raw, self.archive)
        self.assertEqual(result['state'], 'committed')
        self.assertTrue((self.state / 'helper' / 'manager_update_helper.py').is_file())
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assertEqual(self.launcher.read_bytes(), b'# synthetic code\n')
        again = self.transaction().install()
        self.assertTrue(again['already_installed'])
        self.assert_data()

    def test_failed_signature_restores_exact_app_and_removes_helper(self):
        from app_bundle_backup import inventory
        before = inventory(self.app)
        result = self.transaction(signer=lambda *_a, **_k: False).install(
            self.raw, self.archive)
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(inventory(self.app), before)
        self.assertFalse((self.state / 'helper').exists())
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assert_data()

    def test_interruption_recovers_original_without_new_release(self):
        from app_bundle_backup import inventory
        before = inventory(self.app)
        def interrupt(*_args, **_kwargs):
            raise KeyboardInterrupt('simulated interruption')
        with self.assertRaises(KeyboardInterrupt):
            self.transaction(signer=interrupt).install(self.raw, self.archive)
        self.assertTrue((self.state / 'maintenance.ticket').exists())
        result = self.transaction().install()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(inventory(self.app), before)
        self.assertFalse((self.state / 'helper').exists())
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assert_data()

    def test_interrupted_helper_cleanup_resumes_without_recursive_delete(self):
        from app_bundle_backup import inventory
        before = inventory(self.app)
        with self.assertRaises(KeyboardInterrupt):
            self.transaction(signer=lambda *_a, **_k: (_ for _ in ()).throw(
                KeyboardInterrupt())).install(self.raw, self.archive)
        record = json.loads((self.state / 'manager-capability.json').read_text())
        retired = self.state / ('helper-rollback-' + record['id'])
        (self.state / 'helper').rename(retired)
        (retired / 'manager_update_helper.py').unlink()
        result = self.transaction().install()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertFalse(retired.exists())
        self.assertEqual(inventory(self.app), before)
        self.assert_data()


if __name__ == '__main__':
    unittest.main()
