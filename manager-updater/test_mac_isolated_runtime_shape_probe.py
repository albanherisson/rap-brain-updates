import unittest

from mac_isolated_runtime_shape_probe import inspect


class ShapeTests(unittest.TestCase):
    def test_describes_port_without_running_source(self):
        shape, imports = inspect(b'import sqlite3\nPORT = 8765\nraise RuntimeError("not run")\n')
        self.assertEqual(shape, 'Constant(value=8765)')
        self.assertEqual(imports, ['sqlite3'])

    def test_ambiguous_port_refuses(self):
        with self.assertRaisesRegex(ValueError, 'port_shape_unknown'):
            inspect(b'PORT = 8765\nPORT = 8766\n')
