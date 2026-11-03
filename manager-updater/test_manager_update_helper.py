"""The handoff helper never enters a transaction before exit/offline proof."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from creative_release import Refused
from manager_update_helper import report_result, run_handoff, staged_release


class ManagerHelperTest(unittest.TestCase):
    ID = 'b' * 32

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'source'
        self.source.mkdir()
        self.launcher = root / 'Manager.app' / 'Contents' / 'Resources' / 'launch_manager.py'
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_bytes(b'old')
        self.state = root / 'state'
        self.state.mkdir(mode=0o700)
        folder = self.state / ('handoff-' + self.ID)
        folder.mkdir(mode=0o700)
        (folder / 'release.json').write_bytes(b'{"signed":true}')
        (folder / 'release.zip').write_bytes(b'archive')
        (folder / 'release.json').chmod(0o600)
        (folder / 'release.zip').chmod(0o600)

    def test_private_stage_only(self):
        self.assertEqual(staged_release(self.state, self.ID),
                         (b'{"signed":true}', b'archive'))
        with self.assertRaises(Refused):
            staged_release(self.state, '../not-an-id')
        (self.state / ('handoff-' + self.ID) / 'release.zip').chmod(0o644)
        with self.assertRaises(Refused):
            staged_release(self.state, self.ID)

    def test_result_survives_parent_http_exit_without_exposing_payload(self):
        report = report_result(self.state, self.ID,
            {'state': 'committed', 'backup_id': self.ID,
             'secret': 'do not expose'})
        self.assertEqual(report, {'attempt': self.ID, 'state': 'committed',
            'installation_performed': True, 'backup_id': self.ID})
        saved = self.state / 'manager-handoff-result.json'
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b'secret', saved.read_bytes())
        with self.assertRaises(Refused):
            report_result(self.state, self.ID, {'state': 'running'})

    def test_no_stage_read_if_parent_not_confirmed(self):
        with patch('manager_update_helper.staged_release') as read_stage:
            def refused(*_args): raise Refused('parent_still_running')
            with self.assertRaises(Refused):
                run_handoff(self.source, self.launcher, self.state, self.ID,
                            3, 'a'*64, 42, 'start', waiter=refused,
                            offline=lambda *_: None)
            read_stage.assert_not_called()

    def test_verified_candidate_commits_after_offline_proof(self):
        calls = []
        waiter = lambda *_: calls.append('parent_exited')
        offline = lambda *_: calls.append('offline')
        tx = Mock()
        tx.install_handed_off.return_value = {'state': 'committed'}
        with (patch('strict_json.parse_signed_json',
                    return_value={'signed_payload': {'issued_at': 100}}),
              patch('manager_update_helper.verify_manifest', return_value={'ok': True}),
              patch('manager_update_helper.verify_archive', return_value={})):
            result = run_handoff(self.source, self.launcher, self.state,
                self.ID, 3, 'a'*64, 42, 'start', waiter=waiter,
                offline=offline, lifecycle_factory=lambda *_a, **_k: object(),
                transaction_factory=lambda *_: tx)
        self.assertEqual(calls, ['parent_exited', 'offline'])
        self.assertEqual(result['state'], 'committed')
        tx.install_handed_off.assert_called_once()

    def test_corrupt_archive_aborts_only_unchanged_original(self):
        tx = Mock()
        tx.abort_handoff_before_journal.return_value = {'state': 'aborted'}
        with (patch('strict_json.parse_signed_json',
                    return_value={'signed_payload': {'issued_at': 100}}),
              patch('manager_update_helper.verify_manifest', return_value={'ok': True}),
              patch('manager_update_helper.verify_archive',
                    side_effect=Refused('archive_changed'))):
            result = run_handoff(self.source, self.launcher, self.state,
                self.ID, 3, 'a'*64, 42, 'start', waiter=lambda *_: True,
                offline=lambda *_: True,
                lifecycle_factory=lambda *_a, **_k: object(),
                transaction_factory=lambda *_: tx)
        self.assertEqual(result['state'], 'aborted')
        tx.install_handed_off.assert_not_called()
        tx.abort_handoff_before_journal.assert_called_once()


if __name__ == '__main__':
    unittest.main()
