import unittest

from creative_release import Refused, digest
from isolated_runtime_port import disposable_port_copy


class IsolatedPortTests(unittest.TestCase):
    def test_only_disposable_listener_changes(self):
        original = b'PORT = 8765\nMESSAGE = "8765 stays"\n'
        result = disposable_port_copy(original, digest(original), 18765)
        self.assertEqual(result, b'PORT = 18765\nMESSAGE = "8765 stays"\n')
        self.assertEqual(original, b'PORT = 8765\nMESSAGE = "8765 stays"\n')

    def test_unknown_or_duplicate_declaration_refuses(self):
        for source in (b'PORT = int("8765")\n', b'PORT = 8765\nPORT = 8765\n',
                       b'PORT = 8766\n', b'PORT = True\n'):
            with self.subTest(source=source), self.assertRaises(Refused):
                disposable_port_copy(source, digest(source), 18765)

    def test_source_and_active_port_must_be_pinned(self):
        original = b'PORT = 8765\n'
        for expected, port in ((digest(b'other'), 18765), (digest(original), 8765)):
            with self.assertRaises(Refused):
                disposable_port_copy(original, expected, port)
