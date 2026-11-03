"""Copy-only Manager bridge and authenticated route smoke tests."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from beta14_one_click_candidate import prepare_launcher as creative_launcher
from beta14_one_click_candidate import prepare_dashboard as creative_dashboard
from manager_update_ui_candidate import (PARENT_HANDLER, prepare_launcher,
                                         prepare_dashboard)


ARCHIVE = Path(__file__).resolve().parents[2] / 'evidence' / 'RapBrainManager_App_Beta14.zip'


class ParentBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        namespace = {'json': json, 'Path': Path, '__file__': str(self.root / 'launcher.py')}
        exec(PARENT_HANDLER, namespace)
        self.handler = namespace['handle_manager_update_request']

    def test_invalid_request_never_stops_server(self):
        (self.root / 'manager-update-request.json').write_text('{"action":"other"}')
        with patch('manager_update_parent.prepare_handoff') as handoff:
            self.assertFalse(self.handler(self.root, self.root, self.root, {}))
        handoff.assert_not_called()
        result = json.loads((self.root / 'manager-update-result.json').read_text())
        self.assertEqual(result['state'], 'refused')

    def test_parent_uses_retained_state_and_releases_for_exit(self):
        (self.root / 'manager-update-request.json').write_text(
            '{"action":"install-signed-manager"}')
        handoff = Mock()
        state = {'process': object()}
        with patch('manager_update_parent.prepare_handoff', return_value=handoff) as prepare:
            self.assertTrue(self.handler(self.root, self.root, self.root, state))
        prepare.assert_called_once_with(self.root, self.root / 'launcher.py',
            self.root / 'secure-update', state,
            self.root / 'secure-update' / 'helper' / 'manager_update_helper.py')
        handoff.release_for_parent_exit.assert_called_once()


class CopyLauncherTest(unittest.TestCase):
    def setUp(self):
        if not ARCHIVE.is_file():
            self.skipTest('owner Beta 14 archive unavailable in this checkout')
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with ZipFile(ARCHIVE) as archive:
            self.raw_launcher = archive.read(next(name for name in archive.namelist()
                                                  if name.endswith('/launch_manager.py')))
            self.raw_dashboard = archive.read(next(name for name in archive.namelist()
                                                   if name.endswith('/dashboard_beta14.html')))

    def test_exact_baseline_and_copy_only_smoke(self):
        with ZipFile(ARCHIVE) as archive:
            archive.extractall(self.root)
        app = next(self.root.rglob('Rap Brain Manager Beta 14.app'))
        resources = app / 'Contents' / 'Resources'
        launcher = resources / 'launch_manager.py'
        dashboard = resources / 'dashboard_beta14.html'
        candidate = prepare_launcher(creative_launcher(self.raw_launcher))
        page = prepare_dashboard(creative_dashboard(self.raw_dashboard))
        launcher.write_bytes(candidate)
        dashboard.write_bytes(page)
        source = self.root / 'source'
        source.mkdir()
        (source / 'server.py').write_bytes(b'# disposable\n')
        result = subprocess.run([sys.executable, '-B', str(launcher), '--smoke-test',
            '--rap-brain-dir', str(source), '--backup-dir', str(self.root / 'backups')],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertEqual((source / 'server.py').read_bytes(), b'# disposable\n')
        self.assertIn(b'Installer la mise \xc3\xa0 jour sign\xc3\xa9e', page)
        with self.assertRaises(ValueError):
            prepare_launcher(candidate + b' ')
        with self.assertRaises(ValueError):
            prepare_dashboard(page + b' ')


if __name__ == '__main__':
    unittest.main()
