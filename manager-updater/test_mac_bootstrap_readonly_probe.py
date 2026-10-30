from pathlib import Path
import tempfile
import unittest

from mac_bootstrap_readonly_probe import PINNED, digest, safe_read


class ProbeTests(unittest.TestCase):
    def test_pinned_preparers_match_repository_bytes(self):
        root = Path(__file__).parent
        for name, expected in PINNED.items():
            self.assertEqual(digest((root / name).read_bytes()), expected)

    def test_changed_or_symlinked_source_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            file = root / 'server.py'
            file.write_bytes(b'expected')
            self.assertEqual(safe_read(file, digest(b'expected')), b'expected')
            with self.assertRaisesRegex(ValueError, 'fingerprint_changed'):
                safe_read(file, digest(b'other'))
            link = root / 'link.py'
            link.symlink_to(file)
            with self.assertRaisesRegex(ValueError, 'symlink_refused'):
                safe_read(link, digest(b'expected'))


if __name__ == '__main__':
    unittest.main()
