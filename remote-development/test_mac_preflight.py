import tempfile
import unittest
from pathlib import Path

from mac_preflight import inspect


class PreflightTest(unittest.TestCase):
    def test_reads_only_expected_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            app = home / "Downloads" / "rap-brain"
            (app / "data").mkdir(parents=True)
            (app / "server.py").write_bytes(b"test server")
            (app / "data" / "rapbrain.sqlite3").write_bytes(b"private")
            result = inspect(home, which=lambda name: "/bin/git" if name == "git" else None,
                             system=lambda: "Darwin")
            self.assertEqual(result["platform"], "Darwin")
            self.assertTrue(result["database_present"])
            self.assertTrue(result["git_available"])
            self.assertFalse(result["ollama_available"])
            self.assertNotIn(str(home), str(result))
            self.assertNotIn("private", str(result))
            self.assertEqual(len(result["server_sha256"]), 64)

    def test_symlinked_server_is_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            app = home / "Downloads" / "rap-brain"
            app.mkdir(parents=True)
            secret = home / "secret"
            secret.write_bytes(b"secret")
            (app / "server.py").symlink_to(secret)
            self.assertIsNone(inspect(home, which=lambda _: None)["server_sha256"])


if __name__ == "__main__":
    unittest.main()
