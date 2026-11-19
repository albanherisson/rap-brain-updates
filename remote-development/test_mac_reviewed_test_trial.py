import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mac_reviewed_test_trial as reviewed
from mac_private_source_trial import MANIFEST


class ReviewedTestTrialTest(unittest.TestCase):
    def fixture(self, root):
        home = Path(root)
        bridge = home / "Library" / "Application Support" / "RapBrainRemoteBridge"
        bridge.mkdir(parents=True)
        sources = {"rap_brain/server.py": b"x = 1\n",
                   reviewed.MODULE_PATH: b"def verified_pair(a,b): return False\n",
                   reviewed.TEST_PATH: b"import unittest\n"}
        entries = [{"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
                   for name, body in sorted(sources.items())]
        raw = json.dumps({"schema": "rapbrain-private-source-v1", "files": entries,
                          "server_sha256": hashlib.sha256(sources["rap_brain/server.py"]).hexdigest()}).encode()
        sources[MANIFEST] = raw
        return home, bridge, sources

    def patches(self, sources):
        return (patch.object(reviewed, "MANIFEST_SHA256", hashlib.sha256(sources[MANIFEST]).hexdigest()),
                patch.object(reviewed, "SERVER_SHA256", hashlib.sha256(sources["rap_brain/server.py"]).hexdigest()),
                patch.object(reviewed, "MODULE_SHA256", hashlib.sha256(sources[reviewed.MODULE_PATH]).hexdigest()),
                patch.object(reviewed, "TEST_SHA256", hashlib.sha256(sources[reviewed.TEST_PATH]).hexdigest()))

    def test_failure_does_not_leave_source_copy(self):
        with tempfile.TemporaryDirectory() as root:
            home, bridge, sources = self.fixture(root)
            context = self.patches(sources)
            for p in context: p.start()
            try:
                with self.assertRaisesRegex(RuntimeError, "Tests revus échoués"):
                    reviewed.run_reviewed_test("fake", home=home,
                        fetch=lambda path, token, commit: sources[path],
                        call=lambda *args, **kwargs: SimpleNamespace(returncode=1))
            finally:
                for p in reversed(context): p.stop()
            self.assertEqual(list(bridge.iterdir()), [])

    def test_unreviewed_code_never_starts_subprocess(self):
        with tempfile.TemporaryDirectory() as root:
            home, bridge, sources = self.fixture(root)
            context = self.patches(sources)
            for p in context: p.start()
            called = []
            try:
                sources[reviewed.TEST_PATH] = b"print('changed')\n"
                with self.assertRaisesRegex(RuntimeError, "Source différente"):
                    reviewed.run_reviewed_test("fake", home=home,
                        fetch=lambda path, token, commit: sources[path],
                        call=lambda *args, **kwargs: called.append(True))
            finally:
                for p in reversed(context): p.stop()
            self.assertEqual(called, [])
            self.assertEqual(list(bridge.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
