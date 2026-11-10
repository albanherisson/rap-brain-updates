import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from mac_prepare_source_review import prepare


class ReviewPackageTest(unittest.TestCase):
    def fixtures(self, root, server=b"test server"):
        home = Path(root)
        app = home / "Downloads" / "rap-brain"
        manager = home / "Applications" / "Rap Brain Manager.app"
        app.mkdir(parents=True)
        manager.mkdir(parents=True)
        (app / "server.py").write_bytes(server)
        (app / "data").mkdir()
        (app / "data" / "rapbrain.sqlite3").write_bytes(b"PRIVATE DATABASE")
        (manager / "manager.py").write_bytes(b"manager code")
        return home, app

    def test_only_sources_are_packaged(self):
        with tempfile.TemporaryDirectory() as root:
            home, _ = self.fixtures(root)
            target = home / "review.zip"
            result = prepare(home, target, hashlib.sha256(b"test server").hexdigest())
            self.assertEqual(result["files"], 2)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(sorted(archive.namelist()),
                                 ["_manifest.json", "manager_app/manager.py", "rap_brain/server.py"])
                self.assertNotIn(b"PRIVATE DATABASE", archive.read("_manifest.json"))

    def test_detected_secret_aborts_before_creating_archive(self):
        with tempfile.TemporaryDirectory() as root:
            home, app = self.fixtures(root)
            (app / "leaky.py").write_bytes(b"github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ12345")
            target = home / "review.zip"
            with self.assertRaisesRegex(RuntimeError, "Secret potentiel"):
                prepare(home, target, hashlib.sha256(b"test server").hexdigest())
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
