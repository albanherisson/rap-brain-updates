import tempfile
import unittest
from pathlib import Path

from mac_source_inventory import classify, scan_root


class InventoryTest(unittest.TestCase):
    def test_source_and_private_files_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "server.py").write_text("code")
            (root / "data").mkdir()
            (root / "data" / "rapbrain.sqlite3").write_bytes(b"private")
            (root / "settings.json").write_text("private config")
            (root / "outside").symlink_to(root.parent, target_is_directory=True)
            summary = scan_root(root)
            self.assertEqual(summary["counts"]["source_candidate"], 1)
            self.assertEqual(summary["counts"]["private_data"], 1)
            self.assertEqual(summary["counts"]["review_required"], 1)
            self.assertEqual(summary["source_paths"], ["server.py"])
            self.assertNotIn("private config", str(summary))

    def test_credentials_win_over_source_extension(self):
        self.assertEqual(classify(Path("publisher_private.py")), "private_data")
        self.assertEqual(classify(Path("github_token.py")), "private_data")
        self.assertEqual(classify(Path("config.env")), "private_data")


if __name__ == "__main__":
    unittest.main()
