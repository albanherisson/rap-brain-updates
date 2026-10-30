from pathlib import Path
import tempfile
import unittest

from creative_release import Refused, digest
from isolated_runtime_stage import stage_python_closure


class StageTests(unittest.TestCase):
    def test_only_python_closure_is_copied(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            original = b'import creative_engine\nprint("original")\n'
            (source / 'server.py').write_bytes(original)
            (source / 'creative_engine.py').write_bytes(b'import creative_rag\n')
            (source / 'creative_rag.py').write_bytes(b'VALUE = 1\n')
            (source / 'data').mkdir()
            (source / 'data' / 'rapbrain.sqlite3').write_bytes(b'private database')
            target = root / 'disposable'
            result = stage_python_closure(source, target, b'import creative_engine\n',
                                          digest(original))
            self.assertEqual(set(result), {'server.py', 'creative_engine.py',
                                           'creative_rag.py'})
            self.assertFalse((target / 'data').exists())
            self.assertEqual((source / 'data' / 'rapbrain.sqlite3').read_bytes(),
                             b'private database')

    def test_refuses_changed_baseline_and_symlinked_module(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            original = b'import helper\n'
            (source / 'server.py').write_bytes(original)
            (source / 'helper.py').symlink_to(source / 'server.py')
            with self.assertRaises(Refused):
                stage_python_closure(source, root / 'one', original, digest(b'other'))
            with self.assertRaises(Refused):
                stage_python_closure(source, root / 'two', original, digest(original))
            self.assertFalse((root / 'two').exists())
