import errno
import hashlib
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_install_agent import FILES, PRIVATE_FILE, REVIEWED_FILE, MANAGER_LAB_FILE, MANAGER_INVENTORY_FILE, install, legacy_plist, paths, plist, put_new_or_same, upgrade, upgrade_private_trial, upgrade_source_validation, upgrade_reviewed_test, upgrade_manager_lab, upgrade_manager_inventory, upgrade_manager_process
from mac_install_agent import upgrade_manager_install_requests, upgrade_manager_remote_update_trial


class InstallTest(unittest.TestCase):
    def test_remote_install_upgrade_rolls_back_added_files_and_allows_repeat(self):
        for fail in (True, False):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as root:
                home, source = Path(root) / "home", Path(root) / "source"
                data, agent = paths(home)
                data.mkdir(parents=True)
                agent.parent.mkdir(parents=True)
                source.mkdir()
                (data / "mac_bridge.py").write_bytes(b"old")
                (source / "mac_bridge.py").write_bytes(b"new")
                (source / "manager_remote_request.py").write_bytes(b"new module")
                agent.write_bytes(plistlib.dumps(plist(data, sys.executable)))
                calls = []
                codes = iter([0, 13, 0] if fail else [0, 0])
                def fake(args, **kwargs):
                    calls.append(args[1])
                    return subprocess.CompletedProcess(args, next(codes))
                with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                     patch("mac_install_agent.ollama_executable", return_value=None), \
                     patch("mac_install_agent.keychain_token"), \
                     patch("mac_install_agent.private_keychain_token"), \
                     patch("mac_install_agent.REMOTE_TRIAL_INSTALLED_SHA",
                           {"mac_bridge.py": hashlib.sha256(b"old").hexdigest()}), \
                     patch("mac_install_agent.REMOTE_INSTALL_BRIDGE_SHA", hashlib.sha256(b"new").hexdigest()), \
                     patch("mac_install_agent.REMOTE_INSTALL_FILES",
                           {"manager_remote_request.py": hashlib.sha256(b"new module").hexdigest()}):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, "ancien agent restauré"):
                            upgrade_manager_install_requests(home, source, call=fake)
                        self.assertEqual(calls, ["bootout", "bootstrap", "bootstrap"])
                    else:
                        upgrade_manager_install_requests(home, source, call=fake)
                        upgrade_manager_install_requests(home, source, call=fake)
                        self.assertEqual(calls, ["bootout", "bootstrap"])
                self.assertEqual((data / "mac_bridge.py").read_bytes(), b"old" if fail else b"new")
                self.assertEqual((data / "manager_remote_request.py").exists(), not fail)

    def test_remote_trial_upgrade_checks_incoming_hash_and_only_replaces_bridge(self):
        with tempfile.TemporaryDirectory() as root:
            home, source = Path(root) / "home", Path(root) / "source"
            data, agent = paths(home)
            data.mkdir(parents=True)
            agent.parent.mkdir(parents=True)
            source.mkdir()
            old = {"mac_bridge.py": b"old bridge", MANAGER_INVENTORY_FILE: b"old inventory"}
            for name, content in old.items():
                (data / name).write_bytes(content)
            hashes = {name: hashlib.sha256(content).hexdigest() for name, content in old.items()}
            before = plistlib.dumps(plist(data, sys.executable))
            agent.write_bytes(before)
            incoming = source / "mac_bridge.py"
            incoming.write_bytes(b"new bridge")
            calls = []
            def fake(args, **kwargs):
                calls.append(args[1])
                return subprocess.CompletedProcess(args, 0)
            with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                 patch("mac_install_agent.MANAGER_PROCESS_INSTALLED_SHA", hashes), \
                 patch("mac_install_agent.ollama_executable", return_value=None), \
                 patch("mac_install_agent.keychain_token"), \
                 patch("mac_install_agent.private_keychain_token"):
                with self.assertRaisesRegex(RuntimeError, "Empreinte"):
                    upgrade_manager_remote_update_trial(home, source, call=fake)
                self.assertEqual(calls, [])
                with patch("mac_install_agent.REMOTE_MANAGER_BRIDGE_SHA",
                           hashlib.sha256(incoming.read_bytes()).hexdigest()):
                    upgrade_manager_remote_update_trial(home, source, call=fake)
            self.assertEqual(calls, ["bootout", "bootstrap"])
            self.assertEqual(agent.read_bytes(), before)
            self.assertEqual((data / MANAGER_INVENTORY_FILE).read_bytes(), old[MANAGER_INVENTORY_FILE])
            self.assertEqual((data / "mac_bridge.py").read_bytes(), b"new bridge")

    def test_definition_has_no_token_and_uses_stable_home(self):
        with tempfile.TemporaryDirectory() as root:
            data, agent = paths(root)
            definition = plist(data, "/usr/bin/python3")
            self.assertEqual(definition["ProgramArguments"][-1], "--watch-keychain")
            self.assertTrue(definition["KeepAlive"])
            self.assertNotIn("github_pat_", str(definition))
            self.assertEqual(agent.parent.name, "LaunchAgents")

    def test_install_copies_only_bridge_preflight_and_private_trial(self):
        with tempfile.TemporaryDirectory() as root:
            home, source = Path(root) / "home", Path(root) / "source"
            source.mkdir()
            for name in FILES + (PRIVATE_FILE,):
                (source / name).write_bytes(name.encode())
            calls = []
            def fake(args, **kwargs):
                calls.append(args)
                return type("Result", (), {"returncode": 0})()
            with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                 patch("mac_install_agent.keychain_token", return_value="github_pat_test"):
                install(home=home, source=source, python="/usr/bin/python3", call=fake)
            data, agent = paths(home)
            self.assertEqual(sorted(p.name for p in data.iterdir()), sorted(FILES + (PRIVATE_FILE,)))
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

    def test_upgrade_restarts_and_rolls_back_on_failure(self):
        for fail_new in (False, True):
            with tempfile.TemporaryDirectory() as root:
                home, source = Path(root) / "home", Path(root) / "source"
                data, agent = paths(home)
                data.mkdir(parents=True)
                agent.parent.mkdir(parents=True)
                source.mkdir()
                old_hashes = {}
                for name in FILES:
                    original = ("old " + name).encode()
                    (data / name).write_bytes(original)
                    (source / name).write_bytes(("new " + name).encode())
                    old_hashes[name] = hashlib.sha256(original).hexdigest()
                agent.write_bytes(plistlib.dumps(legacy_plist(data, sys.executable)))
                calls = []
                def fake(args, **kwargs):
                    calls.append(args)
                    code = 1 if fail_new and len(calls) == 2 else 0
                    return type("Result", (), {"returncode": code})()
                with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                     patch("mac_install_agent.keychain_token", return_value="github_pat_test"), \
                     patch("mac_install_agent.LEGACY_SHA", old_hashes), \
                     patch("mac_install_agent.ollama_executable", return_value=Path("/opt/homebrew/bin/ollama")):
                    if fail_new:
                        with self.assertRaisesRegex(RuntimeError, "ancien agent restauré"):
                            upgrade(home=home, source=source, call=fake)
                    else:
                        upgrade(home=home, source=source, call=fake)
                self.assertEqual(len(calls), 3 if fail_new else 2)
                self.assertEqual((data / "mac_bridge.py").read_bytes(),
                                 b"old mac_bridge.py" if fail_new else b"new mac_bridge.py")
                definition = plistlib.loads(agent.read_bytes())
                self.assertEqual("EnvironmentVariables" in definition, not fail_new)

    def test_private_upgrade_preserves_plist_and_rolls_back(self):
        for fail_new in (False, True):
            with tempfile.TemporaryDirectory() as root:
                home, source = Path(root) / "home", Path(root) / "source"
                data, agent = paths(home)
                data.mkdir(parents=True)
                agent.parent.mkdir(parents=True)
                source.mkdir()
                old_hashes = {}
                for name in FILES:
                    original = ("old " + name).encode()
                    (data / name).write_bytes(original)
                    old_hashes[name] = hashlib.sha256(original).hexdigest()
                (source / "mac_bridge.py").write_bytes(b"new bridge")
                (source / PRIVATE_FILE).write_bytes(b"new private trial")
                definition = plist(data, sys.executable, Path("/opt/homebrew/bin/ollama"))
                agent.write_bytes(plistlib.dumps(definition))
                before = agent.read_bytes()
                calls = []
                def fake(args, **kwargs):
                    calls.append(args)
                    return type("Result", (), {"returncode": 1 if fail_new and len(calls) == 2 else 0})()
                with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                     patch("mac_install_agent.keychain_token", return_value="github_pat_public"), \
                     patch("mac_install_agent.private_keychain_token", return_value="github_pat_private"), \
                     patch("mac_install_agent.CURRENT_SHA", old_hashes), \
                     patch("mac_install_agent.ollama_executable", return_value=Path("/opt/homebrew/bin/ollama")):
                    if fail_new:
                        with self.assertRaisesRegex(RuntimeError, "ancien agent restauré"):
                            upgrade_private_trial(home=home, source=source, call=fake)
                    else:
                        upgrade_private_trial(home=home, source=source, call=fake)
                self.assertEqual(agent.read_bytes(), before)
                self.assertEqual((data / "mac_bridge.py").read_bytes(), b"old mac_bridge.py" if fail_new else b"new bridge")
                self.assertEqual((data / PRIVATE_FILE).exists(), not fail_new)

    def test_source_validation_upgrade_checks_installed_hash_and_rolls_back(self):
        for fail_new in (False, True):
            with tempfile.TemporaryDirectory() as root:
                home, source = Path(root) / "home", Path(root) / "source"
                data, agent = paths(home)
                data.mkdir(parents=True)
                agent.parent.mkdir(parents=True)
                source.mkdir()
                old_hashes = {}
                for name in FILES + (PRIVATE_FILE,):
                    old = ("verified old " + name).encode()
                    (data / name).write_bytes(old)
                    old_hashes[name] = hashlib.sha256(old).hexdigest()
                    if name != "mac_preflight.py":
                        (source / name).write_bytes(("new " + name).encode())
                definition = plist(data, sys.executable, Path("/opt/homebrew/bin/ollama"))
                agent.write_bytes(plistlib.dumps(definition))
                plist_bytes = agent.read_bytes()
                calls = []
                def fake(args, **kwargs):
                    calls.append(args)
                    return type("Result", (), {"returncode": 1 if fail_new and len(calls) == 2 else 0})()
                with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                     patch("mac_install_agent.keychain_token", return_value="github_pat_public"), \
                     patch("mac_install_agent.private_keychain_token", return_value="github_pat_private"), \
                     patch("mac_install_agent.PRIVATE_TRIAL_SHA", old_hashes), \
                     patch("mac_install_agent.ollama_executable", return_value=Path("/opt/homebrew/bin/ollama")):
                    if fail_new:
                        with self.assertRaisesRegex(RuntimeError, "ancien agent restauré"):
                            upgrade_source_validation(home=home, source=source, call=fake)
                    else:
                        upgrade_source_validation(home=home, source=source, call=fake)
                self.assertEqual(agent.read_bytes(), plist_bytes)
                self.assertEqual((data / "mac_bridge.py").read_bytes(),
                                 b"verified old mac_bridge.py" if fail_new else b"new mac_bridge.py")
                self.assertEqual((data / PRIVATE_FILE).read_bytes(),
                                 ("verified old " + PRIVATE_FILE).encode() if fail_new else ("new " + PRIVATE_FILE).encode())
                self.assertEqual(len(calls), 3 if fail_new else 2)

    def test_reviewed_upgrade_restores_previous_agent_on_start_failure(self):
        for fail_new in (False, True):
            with tempfile.TemporaryDirectory() as root:
                home, source = Path(root) / "home", Path(root) / "source"
                data, agent = paths(home)
                data.mkdir(parents=True)
                agent.parent.mkdir(parents=True)
                source.mkdir()
                hashes = {}
                for name in FILES + (PRIVATE_FILE,):
                    body = ("previous " + name).encode()
                    (data / name).write_bytes(body)
                    hashes[name] = hashlib.sha256(body).hexdigest()
                    if name != "mac_preflight.py":
                        (source / name).write_bytes(("new " + name).encode())
                (source / REVIEWED_FILE).write_bytes(b"reviewed runner")
                agent.write_bytes(plistlib.dumps(plist(data, sys.executable,
                                                          Path("/opt/homebrew/bin/ollama"))))
                before = agent.read_bytes()
                calls = []
                def fake(args, **kwargs):
                    calls.append(args)
                    return type("Result", (), {"returncode": 1 if fail_new and len(calls) == 2 else 0})()
                with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                     patch("mac_install_agent.keychain_token", return_value="github_pat_public"), \
                     patch("mac_install_agent.private_keychain_token", return_value="github_pat_private"), \
                     patch("mac_install_agent.SOURCE_VALIDATION_SHA", hashes), \
                     patch("mac_install_agent.ollama_executable", return_value=Path("/opt/homebrew/bin/ollama")):
                    if fail_new:
                        with self.assertRaisesRegex(RuntimeError, "ancien agent restauré"):
                            upgrade_reviewed_test(home=home, source=source, call=fake)
                    else:
                        upgrade_reviewed_test(home=home, source=source, call=fake)
                self.assertEqual(agent.read_bytes(), before)
                self.assertEqual(len(calls), 3 if fail_new else 2)
                self.assertEqual((data / PRIVATE_FILE).read_bytes(),
                                 ("previous " if fail_new else "new ").encode() + PRIVATE_FILE.encode())
                self.assertEqual((data / REVIEWED_FILE).exists(), not fail_new)

    def test_manager_lab_upgrade_preserves_plist_and_rolls_back(self):
        for fail_new in (False, True):
            with tempfile.TemporaryDirectory() as root:
                home, source = Path(root) / "home", Path(root) / "source"
                data, agent = paths(home)
                data.mkdir(parents=True)
                agent.parent.mkdir(parents=True)
                source.mkdir()
                hashes = {}
                for name in FILES + (PRIVATE_FILE, REVIEWED_FILE):
                    original = ("previous " + name).encode()
                    (data / name).write_bytes(original)
                    hashes[name] = hashlib.sha256(original).hexdigest()
                (source / "mac_bridge.py").write_bytes(b"new bridge")
                (source / MANAGER_LAB_FILE).write_bytes(b"new lab")
                agent.write_bytes(plistlib.dumps(plist(data, sys.executable,
                                                          Path("/opt/homebrew/bin/ollama"))))
                before = agent.read_bytes()
                calls = []
                def fake(args, **kwargs):
                    calls.append(args)
                    return type("Result", (), {"returncode": 5 if fail_new and len(calls) == 2 else 0})()
                with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                     patch("mac_install_agent.keychain_token", return_value="github_pat_public"), \
                     patch("mac_install_agent.private_keychain_token", return_value="github_pat_private"), \
                     patch("mac_install_agent.REVIEWED_INSTALLED_SHA", hashes), \
                     patch("mac_install_agent.ollama_executable", return_value=Path("/opt/homebrew/bin/ollama")):
                    if fail_new:
                        with self.assertRaisesRegex(RuntimeError,
                                                    r"redémarrage launchd \(code 5\).*ancien agent restauré"):
                            upgrade_manager_lab(home=home, source=source, call=fake)
                    else:
                        upgrade_manager_lab(home=home, source=source, call=fake)
                self.assertEqual(agent.read_bytes(), before)
                self.assertEqual(len(calls), 3 if fail_new else 2)
                self.assertEqual((data / "mac_bridge.py").read_bytes(),
                                 b"previous mac_bridge.py" if fail_new else b"new bridge")
                self.assertEqual((data / MANAGER_LAB_FILE).exists(), not fail_new)

    def test_manager_inventory_upgrade_restores_previous_agent_on_failure(self):
        for fail_new in (False, True):
            with tempfile.TemporaryDirectory() as root:
                home, source = Path(root) / "home", Path(root) / "source"
                data, agent = paths(home)
                data.mkdir(parents=True)
                agent.parent.mkdir(parents=True)
                source.mkdir()
                hashes = {}
                for name in FILES + (PRIVATE_FILE, REVIEWED_FILE, MANAGER_LAB_FILE):
                    original = ("previous " + name).encode()
                    (data / name).write_bytes(original)
                    hashes[name] = hashlib.sha256(original).hexdigest()
                (source / "mac_bridge.py").write_bytes(b"new bridge")
                (source / MANAGER_INVENTORY_FILE).write_bytes(b"read-only inventory")
                agent.write_bytes(plistlib.dumps(plist(data, sys.executable,
                                                          Path("/opt/homebrew/bin/ollama"))))
                before = agent.read_bytes()
                calls = []
                def fake(args, **kwargs):
                    calls.append(args)
                    return type("Result", (), {"returncode": 5 if fail_new and len(calls) == 2 else 0})()
                with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                     patch("mac_install_agent.keychain_token", return_value="github_pat_public"), \
                     patch("mac_install_agent.private_keychain_token", return_value="github_pat_private"), \
                     patch("mac_install_agent.MANAGER_LAB_INSTALLED_SHA", hashes), \
                     patch("mac_install_agent.ollama_executable", return_value=Path("/opt/homebrew/bin/ollama")):
                    if fail_new:
                        with self.assertRaisesRegex(RuntimeError, r"redémarrage launchd \(code 5\).*ancien agent restauré"):
                            upgrade_manager_inventory(home=home, source=source, call=fake)
                    else:
                        upgrade_manager_inventory(home=home, source=source, call=fake)
                self.assertEqual(agent.read_bytes(), before)
                self.assertEqual(len(calls), 3 if fail_new else 2)
                self.assertEqual((data / "mac_bridge.py").read_bytes(),
                                 b"previous mac_bridge.py" if fail_new else b"new bridge")
                self.assertEqual((data / MANAGER_INVENTORY_FILE).exists(), not fail_new)

    def test_manager_process_upgrade_retries_eio_and_restores_both_scripts(self):
        cases = (
            ("success", [0], [], 0, None),
            ("transient EIO", [errno.EIO, errno.EIO, 0], [], 2, None),
            ("persistent EIO", [errno.EIO] * 11, [errno.EIO, 0], 11, "code 5"),
            ("other failure", [13], [0], 0, "code 13"),
            ("interrupted retry", [errno.EIO, KeyboardInterrupt()], [0], 1, "KeyboardInterrupt"),
        )
        for label, starts, restores, delays, failure in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as root:
                home, source = Path(root) / "home", Path(root) / "source"
                data, agent = paths(home)
                data.mkdir(parents=True)
                agent.parent.mkdir(parents=True)
                source.mkdir()
                hashes = {}
                for name in FILES + (PRIVATE_FILE, REVIEWED_FILE, MANAGER_LAB_FILE,
                             MANAGER_INVENTORY_FILE):
                    original = ("old " + name).encode()
                    (data / name).write_bytes(original)
                    hashes[name] = hashlib.sha256(original).hexdigest()
                for name in ("mac_bridge.py", MANAGER_INVENTORY_FILE):
                    (source / name).write_bytes(("new " + name).encode())
                agent.write_bytes(plistlib.dumps(plist(data, sys.executable,
                                                          Path("/opt/homebrew/bin/ollama"))))
                before = agent.read_bytes()
                calls = []
                versions = []
                results = iter(starts + restores)

                def fake(args, **kwargs):
                    calls.append(args)
                    if args[1] == "bootout":
                        return subprocess.CompletedProcess(args, 0)
                    versions.append(tuple((data / name).read_bytes()
                                          for name in ("mac_bridge.py", MANAGER_INVENTORY_FILE)))
                    result = next(results)
                    if isinstance(result, KeyboardInterrupt):
                        raise result
                    return subprocess.CompletedProcess(args, result)

                with patch("mac_install_agent.platform.system", return_value="Darwin"), \
                     patch("mac_install_agent.keychain_token", return_value="github_pat_public"), \
                     patch("mac_install_agent.private_keychain_token", return_value="github_pat_private"), \
                     patch("mac_install_agent.MANAGER_INVENTORY_INSTALLED_SHA", hashes), \
                     patch("mac_install_agent.ollama_executable", return_value=Path("/opt/homebrew/bin/ollama")), \
                     patch("mac_install_agent.time.sleep") as sleep:
                    if failure:
                        with self.assertRaisesRegex(RuntimeError, rf"redémarrage launchd \({failure}\).*ancien agent restauré"):
                            upgrade_manager_process(home=home, source=source, call=fake)
                    else:
                        upgrade_manager_process(home=home, source=source, call=fake)
                new = (b"new mac_bridge.py", b"new mac_manager_inventory.py")
                old = (b"old mac_bridge.py", b"old mac_manager_inventory.py")
                self.assertEqual(agent.read_bytes(), before)
                self.assertEqual([args[1] for args in calls], ["bootout"] + ["bootstrap"] * len(starts + restores))
                self.assertEqual(sleep.call_count, delays)
                self.assertEqual(versions, [new] * len(starts) + [old] * len(restores))
                self.assertEqual(tuple((data / name).read_bytes() for name in ("mac_bridge.py", MANAGER_INVENTORY_FILE)),
                                 old if failure else new)


if __name__ == "__main__":
    unittest.main()
