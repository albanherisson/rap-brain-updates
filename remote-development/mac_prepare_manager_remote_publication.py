#!/usr/bin/env python3
"""Prepare signed sequence 15 and prove the remote trigger on disposable Mac copies."""

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import types


REPO = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
REVIEWED = REPO + "fac9dd48ebae97faf0e347573d30a7f73d691cd8/remote-development/"
PREPARER = (REPO + "76865d2d5da606d1c05ffe3d39e11075dd981b3c"
            "/remote-development/mac_prepare_manager_publication.py")
PREPARER_SHA = "db2e26ce9091967b9c814dd2683f3242ef0ec4d9013a5e6dd03147b1d6b1cf2d"
CHANNEL = REPO + "main/manager-stable/manifest.json"
CHANNEL_SHA = "2c974f819617c3846afbb92e68a0a94b3a671205c6a6b8b675680a82a3e871ba"
DASHBOARD_SHA = "cd698665767d379c312ada30cdcbebf0157fba6bda1f3aa501bb982d41872259"
ARCHIVE = "manager-stable/update-15.zip"
OUTPUT = "RapBrain_Manager_Update_15_Candidate.zip"
REMOTE_TRIAL = (REPO + "964665a91aeaca13719782d6a52b8ac8ba7c937d"
                "/remote-development/mac_manager_remote_update_trial.py")
REMOTE_TRIAL_SHA = "495ce0989ed8fd98cb317ef37ac6923ffee5fc1aefad9ff06245c0ac2a5fac9c"
CODE_PINS = {
    "build_remote_manager_launcher.py": "69bcc49602f15a6d3ec9f6bfccaf456361373d407ad7058ca29b372e093c2343",
    "manager_remote_request.py": "bef588df37337ad220d4916057f9c02cd2a5e971ab8f7018a8bda95010031d31",
    "manager_remote_launcher.py": "fea9cbba831ec38559354f6b313cdf80b11c6d174470e260d20e9ad53167a3d5",
    "mac_manager_install_request.py": "59932d451cd67e8537a66130882e8b2a007ed1eba59b53c7e711b81b413d4828",
    "mac_bridge.py": "0567ee64b6c809c09821b858ab79a637749b2f316f05548f66543acac3eae01e",
    "mac_install_agent.py": "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8",
    "mac_preflight.py": "ab32901dc7484ecafeab1d54985119763eb07e00d1e2e9a5e1c4ef51b719546b",
    "mac_private_source_trial.py": "907551daea2195a3e470516999706d3ac4ea68216f787b6b214ef9d39dc72bb0",
    "mac_reviewed_test_trial.py": "644e1c99cea699164cccb6a272bb70c502ec15ff78c515869e4026d8771db414",
    "mac_manager_lab_trial.py": "6f82e1074636c39421791f1ca61bfd844a82af1db7e44753b402f227a6e42c79",
    "mac_manager_inventory.py": "a28ab8cd06b7222377e0a08bc22b85d63ea49f71b4a397330db65d5bf3d5b47e",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_file(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def download(url, digest, limit=50_000):
    import urllib.request
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(limit + 1)
        require(response.geturl() == url and len(raw) <= limit and sha(raw) == digest,
                "remote_publication_source_changed")
    return raw


def patch_once(source, old, new):
    require(source.count(old) == 1, "remote_publication_trial_anchor_changed")
    return source.replace(old, new, 1)


def prepare_harness(root, source, support_raw, *, remote):
    root.mkdir(mode=0o700)
    text = source.decode()
    text = patch_once(text, "    code = checked_bytes(launcher, support.LAUNCHER_SHA)",
                      '    code = checked_bytes(launcher, settings["trial_launcher_sha256"])')
    text = patch_once(text, '    request = namespace["request"]',
                      '    namespace["REMOTE_MANAGER_PORT"] = port\n    request = namespace["request"]')
    text = patch_once(text, '"scenario": scenario,',
                      '"scenario": scenario, "trial_launcher_sha256": support.LAUNCHER_SHA,')
    text = patch_once(text, '(app / DASHBOARD).read_bytes() == payload',
                      '(app / "Contents/Resources" / support.MEMBER.removeprefix("app/")).read_bytes() == payload')
    if remote:
        text = patch_once(text, "    supervisor = {}",
                          "    supervisor = {}\n    forgotten = []")
        text = patch_once(text, "        supervisor.update(state_ref)", """        supervisor.update(state_ref)
        if settings["scenario"] == "rolled_back" and state_ref.get("process") is not None and not forgotten:
            import threading
            forgotten.append(state_ref.pop("process"))
            threading.Thread(target=forgotten[0].wait, daemon=True).start()
""")
    path = root / "handoff_runner.py"
    path.write_text(text)
    (root / "trial_support.py").write_bytes(support_raw)
    return load_file(path)


def signed_launcher(signer, key, baseline, candidate, server_sha):
    from manager_update_release import verify_archive, verify_manifest

    name = "app/launch_manager.py"
    archive = signer.public_zip({name: candidate})
    now = int(time.time())
    manifest = {
        "schema": "rapbrain-manager-production-v1", "sequence": 15,
        "issued_at": now - 1, "expires_at": now + 14 * 86400,
        "production_install_authorized": True, "data_migrations": [],
        "validation": {"macos_copy_install": "passed", "rollback": "passed", "runtime": "passed"},
        "files": [{"path": name, "baseline_sha256": sha(baseline), "payload_sha256": sha(candidate)}],
        "required_server_sha256": server_sha, "archive_url": REPO + "main/" + ARCHIVE,
        "archive_sha256": sha(archive), "archive_bytes": len(archive),
    }
    public, signature = signer.sign(key, signer.canonical(manifest))
    envelope = signer.canonical({
        "signed_payload": manifest, "signature_algorithm": "Ed25519",
        "public_key_base64": base64.b64encode(public).decode("ascii"),
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    })
    checked = verify_manifest(envelope, minimum_sequence=14)
    require(checked == manifest and verify_archive(archive, checked) == {name: candidate},
            "remote_publication_signature_mismatch")
    return envelope, archive, candidate, sha(public)


def exercise_remote_handoff(home, root, runner, support, helper, backup, locale, restart):
    from mac_manager_install_request import advance_install_task, authorize_install_task, parse_install_task
    from manager_remote_request import remote_directory, remote_receipt

    tasks = {}
    released = []

    def authorize(task, request):
        def local_grant(path, token, commit):
            require(path == "remote-development/manager-authorizations/" + request["id"] + ".json"
                    and commit == "a" * 40, "remote_publication_fixture_authorization")
            return json.dumps(request).encode()
        authorize_install_task(task, request, token=lambda: "copy-fixture", fetch=local_grant)

    def open_copy(app):
        require(app.is_relative_to(root), "remote_publication_open_escaped")
        # The harness has already launched this exact copied Manager.
        return True

    def dispatch(_port):
        scenario = next(item for item in ("committed", "rolled_back") if item not in tasks)
        branch = root / scenario
        isolated = branch / "home"
        (isolated / "Library/Application Support/RapBrainRemoteBridge").mkdir(parents=True, mode=0o700)
        raw = (branch / "release.json").read_bytes()
        task = {"schema": "rapbrain-remote-task-v3", "action": "manager_install",
                "id": "trial-" + scenario.replace("_", "-"), "sequence": 16,
                "manifest_sha256": sha(raw), "expected_server_sha256": support.SERVER_SHA,
                "expires_at": int(time.time()) + 900, "authorization_commit": "a" * 40}
        tasks[scenario] = task
        require(advance_install_task(task, home=isolated, authorize=authorize, opener=open_copy)
                == {"state": "pending"}, "remote_publication_task_not_queued")
        if scenario == "rolled_back":
            request = parse_install_task(task)
            directory = remote_directory(isolated)
            def foreign_ready():
                record = remote_receipt(directory, request)
                return True if record and record["state"] == "waiting_foreign_server" else None
            runner.wait_for(foreign_ready, "remote_publication_foreign_server_timeout")
            def stop(home, request):
                require(home == isolated and request == parse_install_task(task),
                        "remote_publication_restart_escaped")
                restart.PORT = json.loads((branch / "control.json").read_bytes())["port"]
                require(restart.prepare_restart(home, support) == "stopped",
                        "remote_publication_foreign_server_not_stopped")
                released.append(True)
            require(advance_install_task(task, home=isolated, authorize=authorize, opener=open_copy,
                                         restart=stop) == {"state": "pending"},
                    "remote_publication_foreign_server_not_released")

    proof = runner.run_trial(home, root, support, helper, backup, locale, dispatch)
    require(proof["status"] == "pass" and released == [True], "remote_publication_remote_trial_failed")
    for scenario, task in tasks.items():
        verdict = advance_install_task(task, home=root / scenario / "home",
                                       authorize=authorize, opener=open_copy)
        require(verdict == {"state": scenario, "manager_reopened": True},
                "remote_publication_handoff_receipt_mismatch")


def prepare(home, root):
    destination = home / "Downloads" / OUTPUT
    require(destination.parent.resolve() == destination.parent and destination.parent.is_dir(),
            "remote_publication_download_folder_invalid")
    require(not os.path.lexists(destination), "remote_publication_candidate_already_exists")
    download(CHANNEL, CHANNEL_SHA, 65_536)
    source = root / "reviewed"
    source.mkdir(mode=0o700)
    for name, pin in CODE_PINS.items():
        (source / name).write_bytes(download(REVIEWED + name, pin))
    sys.path.insert(0, str(source))
    from build_remote_manager_launcher import build_launcher
    from mac_manager_install_request import APP, LAUNCHER, LAUNCHER_SHA, RESTART_SHA, RESTART_URL

    preparer_path = root / "previous_preparer.py"
    preparer_path.write_bytes(download(PREPARER, PREPARER_SHA))
    previous = load_file(preparer_path)
    signer_path = root / "publisher_signer.py"
    signer_path.write_bytes(download(previous.SIGNER_URL, previous.SIGNER_SHA))
    signer = load_file(signer_path)
    button_path = root / "programmatic_request.py"
    button_path.write_bytes(download(REMOTE_TRIAL, REMOTE_TRIAL_SHA))
    button = load_file(button_path)
    restart_path = root / "restart_runner.py"
    restart_path.write_bytes(download(RESTART_URL, RESTART_SHA))
    restart = load_file(restart_path)
    runner_source = download(previous.HANDOFF_URL, previous.HANDOFF_SHA)
    metadata_path = root / "trusted_handoff.py"
    metadata_path.write_bytes(runner_source)
    metadata = load_file(metadata_path)
    support_raw = download(metadata.SUPPORT_URL, metadata.SUPPORT_SHA)
    locale = {}
    exec(compile(download(metadata.LOCALE_URL, metadata.LOCALE_SHA), "locale_candidate.py", "exec"), locale)
    phase_a = root / "bootstrap"
    bootstrap = prepare_harness(phase_a, runner_source, support_raw, remote=False)
    support = bootstrap.load_support(phase_a)
    helper = support.fetch_helper()
    backup = support.fetch_bytes(support.BACKUP_URL, 20_000)
    baseline_path = home / APP / LAUNCHER
    baseline = bootstrap.checked_bytes(baseline_path, support.LAUNCHER_SHA)
    candidate = build_launcher(baseline, (source / "manager_remote_request.py").read_bytes(),
                               (source / "manager_remote_launcher.py").read_bytes())
    require(sha(candidate) == LAUNCHER_SHA, "remote_publication_launcher_hash_mismatch")
    support.DASHBOARD_SHA = DASHBOARD_SHA
    support.MEMBER = "app/launch_manager.py"
    signed = None

    def sign_once(dashboard, _branch):
        nonlocal signed
        require(sha(dashboard) == DASHBOARD_SHA, "remote_publication_dashboard_baseline_changed")
        if signed is None:
            signed = signed_launcher(signer, home / previous.KEY_PATH, baseline, candidate, support.SERVER_SHA)
        return signed

    support.signed_trial = sign_once
    print("Séquence 15 : signature locale et essai de mise à niveau sur copies", flush=True)
    proof = bootstrap.run_trial(home, phase_a, support, helper, backup, locale,
                                lambda port: button.request_update(port, bootstrap, support))
    require(proof["status"] == "pass" and signed is not None, "remote_publication_bootstrap_failed")

    phase_b = root / "remote"
    remote = prepare_harness(phase_b, runner_source, support_raw, remote=True)
    remote_support = types.ModuleType("remote_copy_support")
    ephemeral = patch_once(support_raw.decode(), '"sequence": 14,', '"sequence": 16,')
    exec(compile(ephemeral, "remote_copy_support.py", "exec"), remote_support.__dict__)
    remote_support.DASHBOARD_SHA = DASHBOARD_SHA
    remote_support.LAUNCHER_SHA = LAUNCHER_SHA
    print("Raccordement distant : demande privée, redémarrage et retour arrière sur copies", flush=True)
    exercise_remote_handoff(phase_a / "committed/home", phase_b, remote, remote_support,
                            helper, backup, locale, restart)
    download(CHANNEL, CHANNEL_SHA, 65_536)
    envelope, archive, _payload, _pin = signed
    package = signer.public_zip({"manager-stable/manifest.json": envelope, ARCHIVE: archive})
    previous.export_package(destination, package)

    print("Activation du pont pour les prochaines demandes autorisées", flush=True)
    try:
        upgrade = subprocess.run([sys.executable, "-s", "-B", str(source / "mac_install_agent.py"),
                                  "--upgrade-manager-install-requests"], cwd=source,
                                 stdin=subprocess.DEVNULL, timeout=90)
        bridge_activated = upgrade.returncode == 0
    except (OSError, subprocess.SubprocessError):
        bridge_activated = False
    return {"status": "pass", "sequence": 15, "publisher_signature": "verified",
            "bootstrap_install_and_rollback": "verified_on_copies",
            "remote_install_and_rollback": "verified_on_copies",
            "foreign_server_restart": "verified_on_copy", "bridge_activated": bridge_activated,
            "zip": OUTPUT, "zip_sha256": sha(package)}


def main():
    require(sys.platform == "darwin" and len(sys.argv) == 1, "remote_publication_macos_required")
    with tempfile.TemporaryDirectory(prefix="rapbrain-remote-publication-") as temporary:
        report = prepare(Path.home().resolve(), Path(temporary).resolve())
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        reason = str(error)
        print(json.dumps({"status": "failed", "reason": reason if re.fullmatch(
            r"[a-zA-Z0-9_]+", reason) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
