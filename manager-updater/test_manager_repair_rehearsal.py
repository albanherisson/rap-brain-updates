"""The copy rehearsal never changes the source app or synthetic live data."""
import unittest

from app_bundle_backup import inventory
from manager_repair_rehearsal import rehearse_on_copy
from test_manager_repair_transaction import RepairTransactionTests


class RepairRehearsalTests(unittest.TestCase):
    def test_commit_and_post_switch_rollback_on_separate_copies(self):
        fixture = RepairTransactionTests('test_commit_preserves_synthetic_data_and_verified_backup')
        fixture.setUp()
        try:
            original = inventory(fixture.app)
            data = {p.name: p.read_bytes() for p in
                    (fixture.source / 'data').iterdir()}
            from unittest.mock import patch
            from creative_release import digest
            with patch('manager_repair_release.SERVER', digest(fixture.server)):
                report = rehearse_on_copy(fixture.source, fixture.launcher,
                    fixture.state, fixture.fixture.sign(fixture.fixture.payload),
                    fixture.fixture.archive, pinned_key=fixture.fixture.pin,
                    compiler=lambda *_: b'copy-only native executable',
                    signer=lambda *_a, **_k: True,
                    original_verifier=lambda *_a, **_k: True,
                    restored_verifier=lambda *_a, **_k: True)
            self.assertEqual(report, {'state': 'passed',
                'live_database_opened': False,
                'live_configuration_opened': False,
                'active_files_modified': False})
            self.assertEqual(inventory(fixture.app), original)
            self.assertEqual({p.name: p.read_bytes() for p in
                              (fixture.source / 'data').iterdir()}, data)
        finally:
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
