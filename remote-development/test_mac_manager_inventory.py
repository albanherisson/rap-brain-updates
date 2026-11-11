import hashlib
import tempfile
import unittest
from pathlib import Path

from mac_manager_inventory import inspect, running, RESOURCE_NAMES


class InventoryTest(unittest.TestCase):
    def test_only_fixed_bundle_resources_are_hashed(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            resources = home / "Applications" / "Rap Brain Manager.app" / "Contents" / "Resources"
            resources.mkdir(parents=True)
            (home / "Downloads").mkdir()
            for name in RESOURCE_NAMES:
                (resources / name).write_bytes(name.encode())
            private = home / "Downloads" / "rap-brain" / "data"
            private.mkdir(parents=True)
            (private / "rapbrain.sqlite3").write_bytes(b"private database")
            result = inspect(home)
            self.assertEqual(result["applications_bundle"]["sha256"][RESOURCE_NAMES[0]],
                             hashlib.sha256(RESOURCE_NAMES[0].encode()).hexdigest())
            self.assertFalse(result["beta14_bundle"]["present"])
            self.assertNotIn("private database", str(result))
            self.assertNotIn("rapbrain.sqlite3", str(result))

    def test_symlinked_bundle_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "home"
            home.mkdir()
            other = Path(root) / "elsewhere"
            other.mkdir()
            (home / "Applications").symlink_to(other, target_is_directory=True)
            (home / "Downloads").mkdir()
            with self.assertRaisesRegex(ValueError, "redirigé"):
                inspect(home)

    def test_process_census_returns_only_categories(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            beta = home / "Downloads" / "RapBrainManager_App_Beta14" / "Rap Brain Manager Beta 14.app"
            commands = ("123 /bin/other --secret value\n"
                        "456 " + str(beta / "Contents" / "MacOS" / "RapBrain") + "\n"
                        "789 /usr/bin/python3 " + str(home / "Downloads" / "rap-brain" / "server.py") + "\n")
            calls = []
            def fake(args, **kwargs):
                calls.append(args)
                return type("Result", (), {"returncode": 0, "stdout": commands if len(calls) == 1 else "p789\n",
                                            "stderr": ""})()
            result = running(home, call=fake)
            self.assertTrue(result["beta14_bundle_running"])
            self.assertTrue(result["server_running"])
            self.assertFalse(result["applications_bundle_running"])
            self.assertTrue(result["port_8765_listening"])
            self.assertNotIn("secret", str(result))


if __name__ == "__main__":
    unittest.main()
