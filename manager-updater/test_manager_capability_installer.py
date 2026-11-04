"""The Finder entry authenticates before writes and recovers without network."""
import unittest

from creative_release import Refused
from manager_capability_installer import install_from_channel
from manager_capability_release import ARCHIVE, CHANNEL
from test_manager_capability_transaction import CapabilityTransactionTests


class CapabilityInstallerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = CapabilityTransactionTests('test_commit_and_idempotent_reopen')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_fixed_downloads_and_signed_copy_commit(self):
        calls = []
        def fetch(url, limit):
            calls.append(url)
            return self.fixture.raw if url == CHANNEL else self.fixture.archive
        result = install_from_channel(self.fixture.source, self.fixture.launcher,
            self.fixture.state, downloader=fetch,
            transaction_factory=lambda *_a, **_k: self.fixture.transaction(),
            inspector=self.fixture.offline, pinned_key=self.fixture.signed_fixture.pin)
        self.assertEqual(result['state'], 'committed')
        self.assertEqual(calls, [CHANNEL, ARCHIVE])
        self.fixture.assert_data()

    def test_pending_attempt_recovers_without_download(self):
        def interrupt(*_args, **_kwargs):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.fixture.transaction(signer=interrupt).install(
                self.fixture.raw, self.fixture.archive)
        def no_network(*_args):
            raise AssertionError('recovery_fetched_network')
        result = install_from_channel(self.fixture.source, self.fixture.launcher,
            self.fixture.state, downloader=no_network,
            transaction_factory=lambda *_a, **_k: self.fixture.transaction(),
            inspector=self.fixture.offline, pinned_key=self.fixture.signed_fixture.pin)
        self.assertEqual(result['state'], 'rolled_back')

    def test_tamper_refused_before_state_journal(self):
        with self.assertRaises(Refused):
            install_from_channel(self.fixture.source, self.fixture.launcher,
                self.fixture.state,
                downloader=lambda url, limit: (self.fixture.raw if url == CHANNEL
                                               else self.fixture.archive + b'!'),
                transaction_factory=lambda *_a, **_k: self.fixture.transaction(),
                inspector=self.fixture.offline,
                pinned_key=self.fixture.signed_fixture.pin)
        self.assertFalse((self.fixture.state / 'manager-capability.json').exists())


if __name__ == '__main__':
    unittest.main()
