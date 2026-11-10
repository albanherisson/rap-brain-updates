import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mac_private_source_trial as source


class PrivateSourceTrialTest(unittest.TestCase):
    def fixture(self, root):
        home = Path(root)
        parent = home / "Library" / "Application Support" / "RapBrainRemoteBridge"
        parent.mkdir(parents=True)
        files = {"rap_brain/server.py": b"x = 1\n"}
        files.update({f"rap_brain/module_{index}.py": b"x = 2\n" for index in range(21)})
        entries = [{"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
                   for name, body in sorted(files.items())]
        manifest = json.dumps({"schema": "rapbrain-private-source-v1", "files": entries,
                               "server_sha256": hashlib.sha256(files["rap_brain/server.py"]).hexdigest()}).encode()
        files[source.MANIFEST] = manifest
        return home, parent, files

    def test_verified_copy_is_removed_and_installation_untouched(self):
        with tempfile.TemporaryDirectory() as root:
            home, parent, files = self.fixture(root)
            installed = home / "Downloads" / "rap-brain" / "server.py"
            installed.parent.mkdir(parents=True)
            installed.write_bytes(b"installed remains unchanged")
            with patch.object(source, "MANIFEST_SHA256", hashlib.sha256(files[source.MANIFEST]).hexdigest()), \
                    patch.object(source, "EXPECTED_SERVER", hashlib.sha256(files["rap_brain/server.py"]).hexdigest()):
                result = source.trial("fake", fetch=lambda path, token: files[path], home=home)
            self.assertEqual(result["files_verified"], 22)
            self.assertEqual(result["python_syntax_verified"], 22)
            self.assertEqual(installed.read_bytes(), b"installed remains unchanged")
            self.assertEqual(list(parent.iterdir()), [])

    def test_hash_mismatch_removes_partial_copy(self):
        with tempfile.TemporaryDirectory() as root:
            home, parent, files = self.fixture(root)
            files["rap_brain/module_1.py"] = b"different"
            with patch.object(source, "MANIFEST_SHA256", hashlib.sha256(files[source.MANIFEST]).hexdigest()), \
                    patch.object(source, "EXPECTED_SERVER", hashlib.sha256(files["rap_brain/server.py"]).hexdigest()):
                with self.assertRaisesRegex(RuntimeError, "Source différente"):
                    source.trial("fake", fetch=lambda path, token: files[path], home=home)
            self.assertEqual(list(parent.iterdir()), [])

    def test_rejects_saved_snapshot_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as root:
            _, _, files = self.fixture(root)
            manifest = json.loads(files[source.MANIFEST])
            for path in ("rap_brain/sauvegardes/old.py", "rap_brain/../secret.py"):
                manifest["files"][0]["path"] = path
                raw = json.dumps(manifest).encode()
                with patch.object(source, "MANIFEST_SHA256", hashlib.sha256(raw).hexdigest()), \
                        patch.object(source, "EXPECTED_SERVER", manifest["server_sha256"]):
                    with self.assertRaisesRegex(RuntimeError, "Chemin de source"):
                        source.validated_manifest(raw)


if __name__ == "__main__":
    unittest.main()
