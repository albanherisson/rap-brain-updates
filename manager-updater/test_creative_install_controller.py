"""Parent-side install sequencing on disposable paths; no live install."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from creative_release import Refused
from creative_install_controller import install_owned_creative


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'source'
        self.source.mkdir()
        (self.source / 'server.py').write_bytes(b'isolated guarded server')
        self.state = Path(self.tmp.name) / 'state'

    def test_unowned_server_refuses_before_download(self):
        downloader = Mock()
        transaction = Mock()
        transaction.recover.return_value = None
        with patch('creative_install_controller.bind_owned_launch',
                   side_effect=Refused('unowned_server')):
            with self.assertRaisesRegex(Refused, 'unowned_server'):
                install_owned_creative(self.source, self.state, {}, downloader=downloader,
                    lifecycle_factory=Mock(),
                    transaction_factory=Mock(return_value=transaction))
        downloader.assert_not_called()
        transaction.install.assert_not_called()

    def test_recovery_is_the_whole_click(self):
        downloader = Mock()
        transaction = Mock()
        transaction.recover.return_value = {'state': 'rolled_back'}
        with patch('creative_install_controller.bind_owned_launch') as owned:
            result = install_owned_creative(self.source, self.state, {},
                downloader=downloader, lifecycle_factory=Mock(),
                transaction_factory=Mock(return_value=transaction))
        self.assertEqual(result, {'state': 'rolled_back'})
        downloader.assert_not_called()
        owned.assert_not_called()
        transaction.install.assert_not_called()

    def test_signed_download_after_recovery_and_one_install(self):
        events = []
        transaction = Mock()
        transaction.recover.side_effect = lambda: events.append('recover')
        transaction.install.side_effect = lambda manifest, archive: (
            events.append(('install', manifest, archive)) or {'state': 'committed'})
        downloader = lambda: (events.append('download') or (b'signed', b'archive'))
        with patch('creative_install_controller.bind_owned_launch'):
            result = install_owned_creative(self.source, self.state, {},
                downloader=downloader, lifecycle_factory=Mock(),
                transaction_factory=Mock(return_value=transaction))
        self.assertEqual(result, {'state': 'committed'})
        self.assertEqual(events, ['recover', 'download', ('install', b'signed', b'archive')])


if __name__ == '__main__':
    unittest.main()
