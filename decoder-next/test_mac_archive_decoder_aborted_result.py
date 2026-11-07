"""Check that only a fully proven terminal attempt can be archived."""
import json
from pathlib import Path
import tempfile
import unittest

from mac_archive_decoder_aborted_result import (ATTEMPT, BASELINE, CANDIDATE,
                                                 archive_checked)


class AbortedResultTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.state = root / 'secure-update'
        self.state.mkdir(mode=0o700)
        self.source = root / 'rap-brain'
        self.source.mkdir()
        self.launcher = root / 'Manager.app/Contents/Resources/launch_manager.py'
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_bytes(b'# original\n')
        self.report = {'attempt':ATTEMPT, 'installation_performed':None,
                       'reason':'Refused', 'state':'check_required'}
        self.journal = {'id':ATTEMPT, 'phase':'aborted',
            'schema':'rapbrain-manager-production-v1', 'sequence':4,
            'source':str(self.source), 'launcher':str(self.launcher),
            'server_baseline':BASELINE, 'baselines':{'server.py':BASELINE}}
        self.manifest = {'sequence':4, 'required_server_sha256':BASELINE,
            'files':[{'path':'server.py', 'baseline_sha256':BASELINE,
                      'payload_sha256':CANDIDATE}], 'data_migrations':[]}
        self.receipt = self.state / 'manager-handoff-result.json'
        self.receipt.write_text(json.dumps(self.report))
        self.receipt.chmod(0o600)
        self.calls = []

    def archive(self):
        def verified(name):
            self.calls.append(name)
        return archive_checked(self.state, self.source, self.launcher,
            self.report, self.journal, {'sequence':3}, b'manifest', b'archive',
            verifier=lambda raw:self.manifest,
            archive_verifier=lambda raw, manifest:verified('archive'),
            baseline_verifier=lambda manifest, source, resources:verified('baseline'),
            inventory=lambda app:verified('inventory'),
            signer=lambda app:verified('signature'), fsync=lambda state:verified('fsync'))

    def test_preserves_aborted_result_after_all_checks(self):
        self.assertEqual(self.archive()['state'], 'archived')
        self.assertFalse(self.receipt.exists())
        saved = self.state / ('manager-handoff-result-check-required-' + ATTEMPT + '.json')
        self.assertEqual(json.loads(saved.read_text()), self.report)
        self.assertEqual(self.calls,
                         ['archive','baseline','inventory','signature','fsync'])

    def test_pending_ticket_refuses_without_moving_receipt(self):
        (self.state / 'maintenance.ticket').write_text('pending')
        with self.assertRaisesRegex(ValueError, 'maintenance_still_pending'):
            self.archive()
        self.assertTrue(self.receipt.exists())
        self.assertEqual(self.calls, [])

    def test_nonterminal_journal_refuses_without_moving_receipt(self):
        self.journal['phase'] = 'switch_pending'
        with self.assertRaisesRegex(ValueError, 'aborted_attempt_not_proven'):
            self.archive()
        self.assertTrue(self.receipt.exists())


if __name__ == '__main__':
    unittest.main()
