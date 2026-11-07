"""Recover only a locally staged signed attempt, on synthetic data."""
import hashlib
import json
from pathlib import Path
import unittest

from creative_release import Refused, digest
from manager_update_recovery import recover_existing
from manager_update_release import verify_manifest
import test_manager_update_transaction as fixture_module

IDENTIFIER = fixture_module.IDENTIFIER


class ExistingAttemptRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ManagerTransactionTests(
            methodName='test_handoff_reuses_existing_ticket_and_attempt')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.source
        self.launcher = self.fixture.launcher
        self.state = self.fixture.state
        self.folder = self.state / ('handoff-' + IDENTIFIER)
        self.folder.mkdir(mode=0o700)
        for name, raw in (('release.json', self.fixture.signed),
                          ('release.zip', self.fixture.archive)):
            path = self.folder / name
            path.write_bytes(raw)
            path.chmod(0o600)
        ticket = fixture_module.OfflineFixture.ticket
        (self.state / 'bootstrap-intent.json').write_text(json.dumps({
            'id': IDENTIFIER, 'source': str(self.source),
            'launcher': str(self.launcher),
            'ticket_sha256': hashlib.sha256(ticket).hexdigest()}))
        (self.state / 'bootstrap-intent.json').chmod(0o600)
        (self.state / 'maintenance.ticket').write_bytes(ticket)
        (self.state / 'maintenance.ticket').chmod(0o600)

    def recover(self):
        return recover_existing(self.source, self.launcher, self.state,
            offline=lambda *_: True,
            lifecycle_factory=lambda *_a, **_k: fixture_module.OfflineFixture(self.state, [True]),
            transaction_factory=lambda *_: self.fixture.tx([True]),
            manifest_verifier=lambda raw, **kw: verify_manifest(
                raw, pinned_key=self.fixture.pin, **kw))

    def test_prejournal_recovers_old_code_without_new_download(self):
        result = self.recover()
        self.assertEqual(result['state'], 'aborted')
        self.fixture.assert_code(self.fixture.before)
        self.fixture.assert_data()
        report = json.loads((self.state / 'manager-handoff-result.json').read_text())
        self.assertEqual(report['state'], 'aborted')

    def test_pending_original_journal_recovers_without_installing_candidate(self):
        tx = self.fixture.tx([True])
        record = {'id': IDENTIFIER, 'source': str(self.source),
            'launcher': str(self.launcher), 'schema': self.fixture.manifest['schema'],
            'sequence': 1, 'server_mode': 0o644,
            'server_baseline': digest(self.fixture.before['server.py']),
            'baselines': {entry['path']: entry['baseline_sha256']
                          for entry in self.fixture.manifest['files']}}
        (self.state / IDENTIFIER).mkdir(mode=0o700)
        tx.record(record, 'preparing')
        result = self.recover()
        self.assertEqual(result['state'], 'aborted')
        self.fixture.assert_code(self.fixture.before)
        self.fixture.assert_data()

    def test_other_attempt_refused_without_touching_code_or_data(self):
        intent = self.state / 'bootstrap-intent.json'
        data = json.loads(intent.read_text())
        data['id'] = '4' * 32
        intent.write_text(json.dumps(data))
        with self.assertRaises(Refused):
            self.recover()
        self.fixture.assert_code(self.fixture.before)
        self.fixture.assert_data()


if __name__ == '__main__':
    unittest.main()
