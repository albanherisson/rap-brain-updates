from pathlib import Path
import tempfile
import unittest

from creative_release import Refused, digest
from isolated_runtime_lab import rehearse


class LabTests(unittest.TestCase):
    def test_stages_in_temporary_home_and_removes_it(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            source = root / 'active-source'
            source.mkdir()
            original = b'import helper\nPORT = 8765\n'
            candidate = b'import helper\nPORT = int(__import__("os").getenv("RAP_BRAIN_PORT", "8765"))\n'
            (source / 'server.py').write_bytes(original)
            (source / 'helper.py').write_bytes(b'VALUE = 1\n')
            workspace = root / 'workspace'
            workspace.mkdir()

            def fake_runner(staged, home, expected):
                self.assertEqual(staged, home / 'Downloads' / 'rap-brain')
                self.assertFalse((staged / 'data').exists())
                self.assertEqual(digest((staged / 'server.py').read_bytes()), expected)
                return {'status_ok': True}

            report = rehearse(source, candidate, digest(original), digest(candidate),
                              workspace=workspace, runner=fake_runner)
            self.assertTrue(report['original_server_unchanged'])
            self.assertEqual(report['modules_staged'], 2)
            self.assertEqual(list(workspace.iterdir()), [])
            self.assertEqual((source / 'server.py').read_bytes(), original)

    def test_failed_real_runner_preserves_live_source_and_cleans_lab(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            source = root / 'active-source'
            source.mkdir()
            original = b'import helper\nPORT = 8765\n'
            candidate = b'import helper\nPORT = int(__import__("os").getenv("RAP_BRAIN_PORT", "8765"))\n'
            (source / 'server.py').write_bytes(original)
            (source / 'helper.py').write_bytes(b'VALUE = 1\n')
            workspace = root / 'workspace'
            workspace.mkdir()

            def failing_runner(staged, home, expected):
                self.assertFalse((staged / 'data').exists())
                self.assertEqual(digest((staged / 'server.py').read_bytes()), expected)
                raise Refused('isolated_status_unavailable')

            with self.assertRaisesRegex(Refused, 'isolated_status_unavailable'):
                rehearse(source, candidate, digest(original), digest(candidate),
                         workspace=workspace, runner=failing_runner)
            self.assertEqual((source / 'server.py').read_bytes(), original)
            self.assertEqual((source / 'helper.py').read_bytes(), b'VALUE = 1\n')
            self.assertEqual(list(workspace.iterdir()), [])

    def test_refuses_inaccurate_candidate_before_staging(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            (source / 'server.py').write_bytes(b'original')
            workspace = root / 'workspace'
            workspace.mkdir()
            with self.assertRaises(Refused):
                rehearse(source, b'candidate', digest(b'original'), digest(b'other'),
                         workspace=workspace)
            self.assertEqual(list(workspace.iterdir()), [])
