import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_install_agent import FILES, install, paths, plist, put_new_or_same


class InstallTest(unittest.TestCase):
    def test_definition_has_no_token_and_uses_stable_home(self):
        with tempfile.TemporaryDirectory() as root:
            data, agent = paths(root)
            definition = plist(data, "/usr/bin/python3")
            self.assertEqual(definition["ProgramArguments"][-1], "--watch-keychain")
            self.assertTrue(definition["KeepAlive"])
            self.assertNotIn("github_pat_", str(definition))
            self.assertEqual(agent.parent.name, "LaunchAgents")

    def test_install_copies_only_bridge_and_preflight(self):
        with tempfile.TemporaryDirectory() as root:
            home, source = Path(root) / "home", Path(root) / "source"
            source.mkdir()
            for name in FILES:
                (source / name).write_bytes(name.encode())
            calls = []
            def fake(args, **kwargs):
                calls.append(args)
                return type("Result", (), {"returncode": 0})()
            with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                 patch("mac_install_agent.keychain_token", return_value="github_pat_test"):
                install(home=home, source=source, python="/usr/bin/python3", call=fake)
            data, agent = paths(home)
            self.assertEqual(sorted(p.name for p in data.iterdir()), sorted(FILES))
            self.assertEqual(plistlib.loads(agent.read_bytes())["ProgramArguments"][1], str(data / "mac_bridge.py"))
            self.assertEqual(len(calls), 1)
            self.assertNotIn("github_pat_test", str(calls))

    def test_existing_file_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "mac_bridge.py"
            dest.write_bytes(b"old")
            with self.assertRaises(RuntimeError):
                put_new_or_same(dest, b"new", 0o600)
            self.assertEqual(dest.read_bytes(), b"old")


if __name__ == "__main__":
    unittest.main()
