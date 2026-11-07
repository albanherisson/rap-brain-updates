"""The owner's data paths are excluded from the copy rehearsal."""
import unittest

from app_bundle_backup import inventory
from manager_capability_rehearsal import rehearse_on_copy
from test_manager_capability_transaction import CapabilityTransactionTests


class CapabilityRehearsalTests(unittest.TestCase):
    def test_commit_and_rollback_on_two_copies_with_synthetic_data(self):
        fixture = CapabilityTransactionTests('test_commit_and_idempotent_reopen')
        fixture.setUp()
        try:
            original = inventory(fixture.app)
            report = rehearse_on_copy(fixture.source, fixture.launcher,
                fixture.state, fixture.raw, fixture.archive,
                pinned_key=fixture.signed_fixture.pin,
                signer=lambda *_a, **_k: True,
                restored_verifier=lambda *_a, **_k: True,
                original_verifier=lambda *_a, **_k: True)
            self.assertEqual(report, {'state': 'passed',
                'live_database_opened': False,
                'live_configuration_opened': False,
                'active_files_modified': False})
            self.assertEqual(inventory(fixture.app), original)
            fixture.assert_data()
            self.assertFalse((fixture.state / 'manager-capability.json').exists())
        finally:
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
