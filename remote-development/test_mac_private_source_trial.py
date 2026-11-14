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
                        source.validated_manifest(raw, hashlib.sha256(raw).hexdigest(), manifest["server_sha256"])

    def test_new_commit_and_changed_source_without_installation(self):
        with tempfile.TemporaryDirectory() as root:
            home, parent, files = self.fixture(root)
            changed = b"x = 3\n"
            files["rap_brain/module_1.py"] = changed
            files["rap_brain/test_candidate.py"] = b"import unittest\n"
            manifest = json.loads(files[source.MANIFEST])
            next(e for e in manifest["files"] if e["path"] == "rap_brain/module_1.py")["sha256"] = hashlib.sha256(changed).hexdigest()
            manifest["files"].append({"path": "rap_brain/test_candidate.py", "bytes": len(files["rap_brain/test_candidate.py"]),
                                      "sha256": hashlib.sha256(files["rap_brain/test_candidate.py"]).hexdigest()})
            files[source.MANIFEST] = json.dumps(manifest).encode()
            commit = "b" * 40
            result = source.trial_commit(
                "fake", commit, hashlib.sha256(files[source.MANIFEST]).hexdigest(),
                manifest["server_sha256"],
                fetch=lambda path, token, requested_commit: files[path] if requested_commit == commit else None,
                home=home)
            self.assertEqual(result["source_commit"], commit)
            self.assertEqual(result["files_verified"], 23)
            self.assertTrue(result["temporary_copy_removed"])
            self.assertEqual(list(parent.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
