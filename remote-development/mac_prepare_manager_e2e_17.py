#!/usr/bin/env python3
"""Sign and rehearse the first dashboard update for the repaired Manager."""

import base64
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import zipfile

REPO = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
PREVIOUS = REPO + "fc9829e4fc5e3055491e13d2d163e8e1c121b644/remote-development/mac_prepare_manager_remote_publication.py"
PREVIOUS_SHA = "55fe146219e40c2f312ccd0c06cf270d0a011be602ca576d13143d25488ad3ad"
TRIAL = REPO + "cdb675c3b28ae30f619833fd71490564b630fae2/remote-development/mac_manager_handoff_trial.py"
TRIAL_SHA = "c68d0c9d85a4f82e9d9caf9ef4970fe40bed84098f9b3005d591b62d9bc6b783"
SIGNER = REPO + "39a5718e93d3f9520b4cdeab105cdf7e3f332161/manager-updater/finish_candidate/mac_sign_manager_finish.py"
SIGNER_SHA = "a2b5e388ed2b9c7aebb51b7971fef9092c60f7f2bea6ce4fd49b9efe905acba4"
RESTART = REPO + "708bdc4035dd46a85934a12989fb6ec2ed25741f/remote-development/mac_prepare_manager_restart.py"
RESTART_SHA = "3f1e530d84a821e0105e7c4c3ad3b99f52c6fcec986ef50ec8441e3c8cedf040"
CHANNEL = REPO + "main/manager-stable/manifest.json"
CHANNEL_SHA = "525942b65bb77cd9400ccf08eb9761d7746674da509ad46606db2ec6d66f0daa"
REPAIR = Path("Downloads/RapBrain_Manager_Reopen_16/RapBrain_Manager_Reopen_16_Signed.zip")
REPAIR_SHA = "2f7e23a62584d2d48dd88e8b10c4298984e8dd80518d38ac8d6a0bc0af292cd7"
APP = Path("Downloads/RapBrainManager_App_Beta14/Rap Brain Manager Beta 14.app")
LAUNCHER = Path("Contents/Resources/launch_manager.py")
DASHBOARD = Path("Contents/Resources/dashboard_beta14.html")
STATE = Path("Downloads/RapBrainManagerBackups/secure-update")
BRIDGE = Path("Library/Application Support/RapBrainRemoteBridge")
KEY = Path("Library/Application Support/RapBrainManager/publisher_ed25519.key")
LAUNCHER_SHA = "642dc6d2595cca8f5ad6a189dc7362cca74080344beb9e9c331880b157869c7e"
DASHBOARD_SHA = "cd698665767d379c312ada30cdcbebf0157fba6bda1f3aa501bb982d41872259"
BRIDGE_PINS = {
    "mac_manager_install_request.py": "519dae5e5bfe2de40b700f668d0a55344da60ec72cd6dfda6586addcfbb1767c",
    "mac_private_source_trial.py": "907551daea2195a3e470516999706d3ac4ea68216f787b6b214ef9d39dc72bb0",
    "manager_remote_request.py": "bef588df37337ad220d4916057f9c02cd2a5e971ab8f7018a8bda95010031d31",
}
SEQUENCE = 17
MEMBER = "app/dashboard_beta14.html"
ARCHIVE = "manager-stable/update-17.zip"
OUTPUT = "RapBrain_Manager_Update_17_Candidate.zip"

OLD_OUTCOME = "    write('updatelog',message);"
NEW_OUTCOME = """    const detail=typeof result?.reason==='string' && /^[a-zA-Z0-9_]{1,100}$/.test(result.reason)
      ? '\\nMotif technique : '+result.reason : '';
    write('updatelog',message+detail);"""


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def checked(path, expected, limit=250_000):
    require(path.resolve() == path and path.is_file() and 0 < path.stat().st_size <= limit,
            "e2e17_input_missing_or_unsafe")
    raw = path.read_bytes()
    require(sha(raw) == expected, "e2e17_input_hash_changed")
    return raw


def download(url, expected, limit=65_536):
    import urllib.request

    with urllib.request.urlopen(url, timeout=25) as response:
        raw = response.read(limit + 1)
        require(response.geturl() == url and 0 < len(raw) <= limit and sha(raw) == expected,
                "e2e17_download_changed")
    return raw


def replace_once(source, old, new):
    require(source.count(old) == 1, "e2e17_rehearsal_anchor_changed")
    return source.replace(old, new, 1)


def load_code(path, raw):
    import importlib.util

    path.write_bytes(raw)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def active_helper(home):
    raw = checked(home / REPAIR, REPAIR_SHA)
    with zipfile.ZipFile(io.BytesIO(raw)) as outer:
        with zipfile.ZipFile(io.BytesIO(outer.read("manager-reopen/repair-16.zip"))) as release:
            helper = release.read("helper.zip")
        manifest = json.loads(outer.read("manager-reopen/manifest.json"))["signed_payload"]
    signed = base64.b64decode(manifest["helper_manifest_base64"], validate=True)
    entries = json.loads(signed)["signed_payload"]["files"]
    state = home / STATE
    live = state / "helper"
    require(live.resolve() == live and
            set(p.name for p in live.iterdir()) == set(entries) | {"signed-manifest.json"},
            "e2e17_active_helper_layout_changed")
    require(checked(live / "signed-manifest.json", sha(signed)) == signed,
            "e2e17_active_helper_manifest_changed")
    for name, expected in entries.items():
        checked(live / name, expected)
    accepted = state / "manager-accepted.json"
    require(accepted.resolve() == accepted and accepted.is_file() and accepted.stat().st_size <= 256
            and json.loads(accepted.read_bytes()) == {"sequence": 14},
            "e2e17_accepted_sequence_changed")
    return helper


def dashboard_candidate(raw):
    require(sha(raw) == DASHBOARD_SHA, "e2e17_dashboard_baseline_changed")
    return replace_once(raw.decode("utf-8"), OLD_OUTCOME, NEW_OUTCOME).encode("utf-8")


def make_release(dashboard, support, signer, key, now):
    from manager_update_release import verify_archive, verify_manifest

    payload = dashboard_candidate(dashboard)
    archive = signer.public_zip({MEMBER: payload})
    manifest = {"schema": "rapbrain-manager-production-v1", "sequence": SEQUENCE,
        "issued_at": now - 1, "expires_at": now + 14 * 86400,
        "production_install_authorized": True, "data_migrations": [],
        "validation": {"macos_copy_install": "passed", "rollback": "passed", "runtime": "passed"},
        "files": [{"path": MEMBER, "baseline_sha256": DASHBOARD_SHA, "payload_sha256": sha(payload)}],
        "required_server_sha256": support.SERVER_SHA, "archive_url": REPO + "main/" + ARCHIVE,
        "archive_sha256": sha(archive), "archive_bytes": len(archive)}
    public, signature = signer.sign(key, signer.canonical(manifest))
    signed = signer.canonical({
        "signed_payload": manifest, "signature_algorithm": "Ed25519",
        "public_key_base64": base64.b64encode(public).decode("ascii"),
        "signature_base64": base64.b64encode(signature).decode("ascii")})
    verified = verify_manifest(signed, minimum_sequence=16, now=now)
    require(verified == manifest and verify_archive(archive, verified) == {MEMBER: payload},
            "e2e17_publisher_verification_failed")
    return signed, archive, payload, sha(public)


def configure_harness(root, helper):
    previous_source = download(PREVIOUS, PREVIOUS_SHA).decode("utf-8")
    previous_source = replace_once(previous_source, '"sequence": 16,\n',
                                   '"sequence": 17,\n')
    previous_source = replace_once(previous_source,
        '        require(verdict == {"state": scenario, "manager_reopened": True},\n',
        '''        expected = {"state": scenario, "manager_reopened": True}
        if scenario == "rolled_back":
            expected["reason"] = "manager_health_failed"
        require(verdict == expected,
''')
    previous = load_code(root / "previous.py", previous_source.encode())
    runner_raw = download(TRIAL, TRIAL_SHA)
    metadata = load_code(root / "trusted_handoff.py", runner_raw)
    support_raw = download(metadata.SUPPORT_URL, metadata.SUPPORT_SHA)
    runner_source = runner_raw.decode("utf-8")
    runner_source = replace_once(runner_source, '''    support.stage_helper(helper_zip, backup, directory)
    identity = directory / "process_start_identity.py"
    identity.write_bytes(locale["identity"](identity.read_bytes()))
''', f'''    import io
    import zipfile
    require(sha(helper_zip) == "{sha(helper)}", "e2e17_copy_helper_changed")
    directory.mkdir(mode=0o700)
    with zipfile.ZipFile(io.BytesIO(helper_zip)) as archive:
        for entry in archive.infolist():
            require(re.fullmatch(r"helper/[A-Za-z_][A-Za-z_0-9]*\\.(py|swift)", entry.filename),
                    "e2e17_copy_helper_layout")
            (directory / Path(entry.filename).name).write_bytes(archive.read(entry))
''')
    runner_source = replace_once(runner_source,
        '''    stage_reviewed_helper(support, helper_zip, backup, locale, helper)
    for module in helper.iterdir():''',
        '''    stage_reviewed_helper(support, helper_zip, backup, locale, helper)
    receipt = state / "manager-accepted.json"
    receipt.write_text('{"sequence":14}')
    receipt.chmod(0o600)
    for module in helper.iterdir():''')
    # The corrected launcher's early maintenance exit applies to the separate
    # copies as well. The existing harness redirects their server ports.
    runner = previous.prepare_harness(root / "remote", runner_source.encode(), support_raw, remote=True)
    return previous, runner, runner.load_support(root / "remote")


SMOKE = '''
from pathlib import Path
import sys
path, port = Path(sys.argv[1]), sys.argv[2]
scope = {"__file__": str(path), "__name__": "e2e17_copy"}
exec(compile(path.read_bytes(), str(path), "exec"), scope)
scope["CHILD"] = scope["CHILD"].replace("8765", port)
sys.argv = [str(path), "--smoke-test", "--no-browser"]
raise SystemExit(scope["main"]())
'''


def verify_copy_dashboard(branch):
    home = branch / "home"
    port = json.loads((branch / "control.json").read_bytes())["port"]
    require(1024 <= port <= 65535 and port not in (8765, 11434), "e2e17_copy_port_invalid")
    env = {"HOME": str(home), "TMPDIR": str(branch / "tmp"), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}
    result = subprocess.run([sys.executable, "-I", "-B", "-c", SMOKE, str(home / APP / LAUNCHER), str(port)],
                            env=env, cwd=branch, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
    require(result.returncode == 0 and b'"result": "PASS"' in result.stdout,
            "e2e17_copy_dashboard_reopen_failed")


def prepare(home, root):
    destination = home / "Downloads" / OUTPUT
    require(destination.parent.resolve() == destination.parent and not os.path.lexists(destination),
            "e2e17_destination_unavailable")
    download(CHANNEL, CHANNEL_SHA)
    checked(home / APP / LAUNCHER, LAUNCHER_SHA)
    dashboard = checked(home / APP / DASHBOARD, DASHBOARD_SHA)
    helper = active_helper(home)
    dependencies = root / "bridge"
    dependencies.mkdir(mode=0o700)
    for name, expected in BRIDGE_PINS.items():
        (dependencies / name).write_bytes(checked(home / BRIDGE / name, expected))
    sys.path.insert(0, str(dependencies))
    signer = load_code(root / "publisher_signer.py", download(SIGNER, SIGNER_SHA))
    restart = load_code(root / "restart_runner.py", download(RESTART, RESTART_SHA))
    previous, runner, support = configure_harness(root, helper)
    support.DASHBOARD_SHA = DASHBOARD_SHA
    support.LAUNCHER_SHA = LAUNCHER_SHA

    candidate = None

    def signed_trial(copy_dashboard, _branch):
        nonlocal candidate
        require(copy_dashboard == dashboard, "e2e17_copy_dashboard_baseline_changed")
        if candidate is None:
            candidate = make_release(dashboard, support, signer, home / KEY, int(time.time()))
        return candidate

    support.signed_trial = signed_trial
    print("Séquence 17. Demande distante, installation et retour arrière sur copies.", flush=True)
    previous.exercise_remote_handoff(home, root / "remote", runner, support, helper, None, None, restart)
    for outcome in ("committed", "rolled_back"):
        verify_copy_dashboard(root / "remote" / outcome)
    require(candidate is not None, "e2e17_candidate_missing")
    download(CHANNEL, CHANNEL_SHA)
    checked(home / APP / DASHBOARD, DASHBOARD_SHA)
    signed, archive, payload, _ = candidate
    package = signer.public_zip({"manager-stable/manifest.json": signed, ARCHIVE: archive})
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".rapbrain-e2e17-") as output:
        output.write(package)
        output.flush()
        os.fsync(output.fileno())
        os.link(output.name, destination)
    return {"status": "pass", "sequence": SEQUENCE, "publisher_signature": "verified",
            "remote_copy_install": "committed", "remote_copy_rollback": "rolled_back",
            "rollback_reason": "manager_health_failed", "macos_codesign": "verified",
            "copy_dashboard_reopened": "verified", "synthetic_sqlite_and_config": "preserved",
            "zip": OUTPUT, "zip_sha256": sha(package), "manifest_sha256": sha(signed),
            "dashboard_sha256": sha(payload)}


def main():
    require(sys.platform == "darwin" and len(sys.argv) == 1, "e2e17_macos_required")
    with tempfile.TemporaryDirectory(prefix="rapbrain-e2e17-") as name:
        report = prepare(Path.home().resolve(), Path(name).resolve())
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        reason = str(error)
        print(json.dumps({"status": "failed", "reason": reason if re.fullmatch(
            r"[a-zA-Z0-9_]+", reason) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
