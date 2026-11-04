"""Recognition of the already signed Creative P8 without touching Rap Brain."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from zipfile import ZipFile

from manager_version_label_candidate import (
    BASELINE_LAUNCHER_SHA256, CREATIVE_P8_SHA256,
    _prepare_launcher, prepare_launcher)


CANDIDATE = Path(__file__).resolve().parent.parent / 'manager-capability' / 'capability-1.zip'


class VersionLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with ZipFile(CANDIDATE) as package:
            cls.baseline = package.read('app/launch_manager.py')
        assert hashlib.sha256(cls.baseline).hexdigest() == BASELINE_LAUNCHER_SHA256

    def test_only_exact_installed_launcher_is_accepted(self):
        candidate = prepare_launcher(self.baseline)
        self.assertIn(CREATIVE_P8_SHA256.encode(), candidate)
        self.assertNotEqual(candidate, self.baseline)
        with self.assertRaises(ValueError):
            prepare_launcher(self.baseline + b'\n')
        with self.assertRaises(ValueError):
            prepare_launcher(candidate)

    def test_status_recognizes_only_known_engine_and_preserves_other_fields(self):
        payload = b'synthetic creative engine, no real user data'
        candidate = _prepare_launcher(self.baseline, hashlib.sha256(payload).hexdigest())
        source = candidate.decode()
        start = source.index('m.SOURCE=host_source\n')
        end = source.index('def deny_post(self):', start)
        code = source[start:end]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / 'creative_engine.py'
            engine.write_bytes(payload)
            manager = SimpleNamespace(status=lambda: {'version': 'Version non reconnue',
                                                      'source_ok': True})
            namespace = {'m': manager, 'host_source': root, 'hashlib': hashlib}
            exec(code, namespace)
            self.assertEqual(manager.status(), {'version': 'Beta 8.8 + Creative P8',
                                                'source_ok': True})
            engine.write_bytes(b'unrecognized engine')
            self.assertEqual(manager.status()['version'], 'Version non reconnue')
            engine.unlink()
            self.assertEqual(manager.status()['version'], 'Version non reconnue')
            manager.status = lambda: {'version': 'Beta 8.8', 'source_ok': True}
            exec(code, namespace)
            self.assertEqual(manager.status()['version'], 'Beta 8.8')


if __name__ == '__main__':
    unittest.main()
