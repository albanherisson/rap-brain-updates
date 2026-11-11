from pathlib import Path
import tempfile
import unittest

from creative_release import Refused, digest
from isolated_runtime_port import disposable_environment


PORT_DECLARATION = b"import os\nPORT = int(os.getenv('RAP_BRAIN_PORT', '8765'))\n"


class IsolatedPortTests(unittest.TestCase):
    def test_exact_owner_port_shape_uses_separate_home_and_port(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as home:
            env = disposable_environment(PORT_DECLARATION, digest(PORT_DECLARATION),
                                         18765, home)
            self.assertEqual(env['HOME'], home)
            self.assertEqual(env['RAP_BRAIN_PORT'], '18765')
            self.assertEqual(PORT_DECLARATION,
                             b"import os\nPORT = int(os.getenv('RAP_BRAIN_PORT', '8765'))\n")

    def test_unknown_port_or_active_port_refuses(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as home:
            for source in (b'PORT = 8765\n', b'PORT = int(os.getenv("OTHER", "8765"))\n',
                           PORT_DECLARATION + PORT_DECLARATION):
                with self.subTest(source=source), self.assertRaises(Refused):
                    disposable_environment(source, digest(source), 18765, home)
            with self.assertRaises(Refused):
                disposable_environment(PORT_DECLARATION, digest(PORT_DECLARATION), 8765, home)
            with self.assertRaises(Refused):
                disposable_environment(PORT_DECLARATION, digest(b'other'), 18765, home)
