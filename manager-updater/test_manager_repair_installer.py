"""A failed signature never reaches rehearsal or installation."""
import unittest
from unittest.mock import Mock, patch

from creative_release import Refused, digest
from manager_repair_installer import ARCHIVE, CHANNEL, install_from_channel
from test_manager_repair_transaction import RepairTransactionTests


class RepairInstallerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = RepairTransactionTests('test_commit_preserves_synthetic_data_and_verified_backup')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_invalid_manifest_stops_before_rehearsal_or_app_change(self):
        trial = Mock()
        transaction = Mock()
        with patch('manager_repair_installer.assert_offline', return_value=True):
            with self.assertRaises((Refused, ValueError)):
                install_from_channel(self.fixture.source, self.fixture.launcher,
                    self.fixture.state, downloader=lambda *_: b'invalid',
                    rehearsal=trial,
                    transaction_factory=lambda *_a, **_k: transaction,
                    inspector=self.fixture.inspector,
                    pinned_key=self.fixture.fixture.pin)
        trial.assert_not_called()
        transaction.install.assert_not_called()

    def test_valid_release_rehearses_before_transaction(self):
        calls = []
        def download(url, _limit):
            calls.append(url)
            return (self.fixture.fixture.sign(self.fixture.fixture.payload)
                    if url == CHANNEL else self.fixture.fixture.archive)
        def trial(*_a, **_k):
            calls.append('copy_rehearsal')
            return {'state': 'passed', 'active_files_modified': False,
                    'live_database_opened': False,
                    'live_configuration_opened': False}
        transaction = Mock()
        transaction.install.return_value = {'state': 'committed'}
        with patch('manager_repair_installer.assert_offline', return_value=True), \
                patch('manager_repair_release.SERVER', digest(self.fixture.server)):
            result = install_from_channel(self.fixture.source, self.fixture.launcher,
                self.fixture.state, downloader=download, rehearsal=trial,
                transaction_factory=lambda *_a, **_k: transaction,
                inspector=self.fixture.inspector,
                pinned_key=self.fixture.fixture.pin)
        self.assertEqual(result['state'], 'committed')
        self.assertEqual(calls, [CHANNEL, ARCHIVE, 'copy_rehearsal'])
        transaction.install.assert_called_once()


if __name__ == '__main__':
    unittest.main()
