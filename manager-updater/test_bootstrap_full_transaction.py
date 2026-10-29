"""Complete bootstrap commit and rollback on disposable source/app/data."""
import base64
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from bootstrap_full_release import FILES, PRIMARY
from bootstrap_full_transaction import FullBootstrapTransaction
from bootstrap_runtime_resources import RUNTIME_FILES
from creative_release import canonical, digest
from test_bootstrap_transaction import OfflineFixture, IDENTIFIER


ROOT = Path(__file__).resolve().parent


class FullTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'source'
        data = self.source / 'data'
        data.mkdir(parents=True)
        self.resources = root / 'app'
        self.resources.mkdir()
        self.launcher = self.resources / 'launch_manager.py'
        self.before = {'server.py': b'original server\n',
                       'launch_manager.py': b'original launcher\n',
                       'dashboard_beta14.html': b'original dashboard\n'}
        self.after = {'server.py': b'guarded server\n',
                      'launch_manager.py': b'guarded launcher\n',
                      'dashboard_beta14.html': b'new dashboard\n'}
        self.after.update({name: (ROOT / name).read_bytes() for name in RUNTIME_FILES})
        (self.source / 'server.py').write_bytes(self.before['server.py'])
        (self.source / 'creative_engine.py').write_bytes(b'unchanged engine')
        for name in PRIMARY[1:]:
            (self.resources / name).write_bytes(self.before[name])
        (data / 'ollama_model.json').write_bytes(b'{"model":"fixture"}')
        (data / 'audio.wav').write_bytes(b'untouched')
        with sqlite3.connect(data / 'rapbrain.sqlite3') as con:
            con.execute('CREATE TABLE jobs (status TEXT)')
            con.execute("INSERT INTO jobs VALUES ('done')")
        self.saved_data = {p.name: p.read_bytes() for p in data.iterdir()}
        self.state = root / 'state'
        self.state.mkdir(mode=0o700)
        key = Ed25519PrivateKey.generate()
        pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.pin = digest(pub)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name in FILES:
                archive.writestr(name, self.after[name])
        self.archive = stream.getvalue()
        now = int(time.time())
        manifest = {'schema': 'rapbrain-guarded-bootstrap-v2',
            'sequence': 1, 'issued_at': now - 1, 'expires_at': now + 3600,
            'production_install_authorized': True, 'data_migrations': [],
            'validation': {'isolated_rollback': 'passed', 'macos_runtime': 'passed'},
            'archive_sha256': digest(self.archive), 'archive_bytes': len(self.archive),
            'runtime_sha256': {name: digest(self.after[name]) for name in RUNTIME_FILES}}
        for kind, path in zip(('server', 'launcher', 'dashboard'), PRIMARY):
            manifest['baseline_' + kind + '_sha256'] = digest(self.before[path])
            manifest['candidate_' + kind + '_sha256'] = digest(self.after[path])
        self.signed = canonical({'signed_payload': manifest,
            'signature_algorithm': 'Ed25519',
            'signature_base64': base64.b64encode(key.sign(canonical(manifest))).decode(),
            'public_key_base64': base64.b64encode(pub).decode()})

    def transaction(self, health):
        return FullBootstrapTransaction(self.source, self.launcher, self.state,
            OfflineFixture(self.state, health), pinned_key=self.pin)

    def prepared(self):
        return (patch('bootstrap_full_release.prepare_server',
                      return_value=self.after['server.py']),
                patch('bootstrap_full_release.prepare_launcher',
                      return_value=self.after['launch_manager.py']),
                patch('bootstrap_full_release.prepare_dashboard',
                      return_value=self.after['dashboard_beta14.html']))

    def assert_data_preserved(self):
        self.assertEqual(self.saved_data, {p.name: p.read_bytes()
                         for p in (self.source / 'data').iterdir()})

    def test_signed_commit_installs_all_resources_without_data_changes(self):
        a, b, c = self.prepared()
        with a, b, c:
            result = self.transaction([True]).install(self.signed, self.archive)
        self.assertEqual(result['state'], 'committed')
        for name in FILES:
            path = self.source / name if name == 'server.py' else self.resources / name
            self.assertEqual(path.read_bytes(), self.after[name])
        self.assert_data_preserved()

    def test_failed_health_restores_originals_and_removes_runtime(self):
        a, b, c = self.prepared()
        with a, b, c:
            result = self.transaction([False, True]).install(self.signed, self.archive)
        self.assertEqual(result['state'], 'rolled_back')
        for name in PRIMARY:
            path = self.source / name if name == 'server.py' else self.resources / name
            self.assertEqual(path.read_bytes(), self.before[name])
        for name in RUNTIME_FILES:
            self.assertFalse((self.resources / name).exists())
        self.assert_data_preserved()

    def test_recovery_after_partial_switch_restores_original_pair_and_resources(self):
        self.test_signed_commit_installs_all_resources_without_data_changes()
        # Simulate a crash after some files changed, before the phase advanced.
        self.launcher.write_bytes(self.before['launch_manager.py'])
        (self.resources / RUNTIME_FILES[-1]).unlink()
        journal = self.state / 'bootstrap-transaction.json'
        record = json.loads(journal.read_text())
        record['phase'] = 'switch_pending'
        journal.write_text(json.dumps(record))
        journal.chmod(0o600)
        fixture = OfflineFixture(self.state, [True])
        with fixture.maintenance(self.source, self.launcher):
            a, b, c = self.prepared()
            with a, b, c:
                result = self.transaction([True]).recover()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual((self.source / 'server.py').read_bytes(), self.before['server.py'])
        self.assertEqual(self.launcher.read_bytes(), self.before['launch_manager.py'])
        self.assertFalse(any((self.resources / name).exists() for name in RUNTIME_FILES))
        self.assert_data_preserved()


if __name__ == '__main__':
    unittest.main()
