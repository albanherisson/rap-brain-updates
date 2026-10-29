"""Isolated Beta 14 bridge; no production installation or Mac process stop."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from beta14_one_click_candidate import PARENT_HANDLER, prepare_dashboard, prepare_launcher


ARCHIVE = Path(__file__).resolve().parents[2] / 'evidence' / 'RapBrainManager_App_Beta14.zip'


class OneClickCandidateTests(unittest.TestCase):
    def setUp(self):
        if not ARCHIVE.is_file():
            self.skipTest('owner Beta 14 archive unavailable in this checkout')
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with ZipFile(ARCHIVE) as z:
            self.launcher = z.read(next(n for n in z.namelist()
                                        if n.endswith('/launch_manager.py')))
            self.dashboard = z.read(next(n for n in z.namelist()
                                         if n.endswith('/dashboard_beta14.html')))

    def test_original_bytes_only_and_strict_dashboard_pin(self):
        candidate = prepare_launcher(self.launcher)
        page = prepare_dashboard(self.dashboard)
        self.assertIn(b'/api/rapbrain/creative-install', candidate)
        self.assertIn(b'handle_creative_install_request', candidate)
        self.assertIn(b'onclick="installCreative()"', page)
        with self.assertRaisesRegex(ValueError, 'unexpected_beta14_dashboard'):
            prepare_dashboard(self.dashboard + b' ')

    def test_copy_smoke_still_blocks_original_manager_install(self):
        with ZipFile(ARCHIVE) as z:
            z.extractall(self.root)
        app = next(self.root.rglob('Rap Brain Manager Beta 14.app'))
        resource = app / 'Contents' / 'Resources'
        launcher = resource / 'launch_manager.py'
        dashboard = resource / 'dashboard_beta14.html'
        launcher.write_bytes(prepare_launcher(self.launcher))
        dashboard.write_bytes(prepare_dashboard(self.dashboard))
        fake_source = self.root / 'rap-brain-disposable'
        fake_source.mkdir()
        (fake_source / 'server.py').write_text('# fixture\n')
        result = subprocess.run([sys.executable, '-B', str(launcher), '--smoke-test',
            '--rap-brain-dir', str(fake_source), '--backup-dir', str(self.root / 'backups')],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr[-1000:])
        self.assertTrue(json.loads(result.stdout)['real_manager_mutations_disabled'])
        self.assertEqual((fake_source / 'server.py').read_text(), '# fixture\n')

class ParentHandlerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        namespace = {'json': json}
        exec(PARENT_HANDLER, namespace)
        self.handler = namespace['handle_creative_install_request']

    def test_parent_consumes_request_and_reports_transaction_result(self):
        request = self.root / 'creative-install-request.json'
        request.write_text(json.dumps({'action': 'install-signed-creative'}))
        source = self.root / 'source'
        source.mkdir()
        backups = self.root / 'backups'
        backups.mkdir()
        state = {'owned': 'disposable'}
        with patch('creative_install_controller.install_owned_creative',
                   return_value={'state': 'committed', 'installation_performed': True,
                                 'database_replaced': False}) as install:
            self.handler(
                self.root, source, backups, state)
        install.assert_called_once_with(source, backups / 'secure-update', state)
        self.assertFalse(request.exists())
        result = json.loads((self.root / 'creative-install-result.json').read_text())
        self.assertEqual(result['state'], 'finished')
        self.assertTrue(result['installation_performed'])

    def test_parent_refuses_unexpected_request_without_invoking_installer(self):
        (self.root / 'creative-install-request.json').write_text('{"action":"other"}')
        with patch('creative_install_controller.install_owned_creative') as install:
            self.handler(
                self.root, self.root, self.root, {})
        install.assert_not_called()
        result = json.loads((self.root / 'creative-install-result.json').read_text())
        self.assertEqual(result['state'], 'refused')


if __name__ == '__main__':
    unittest.main()
