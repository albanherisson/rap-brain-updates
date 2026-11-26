#!/usr/bin/env python3
"""Rehearse only the signed Manager copy without Ollama or installation."""

import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import traceback
import urllib.request
import zipfile

TASK_URL = ("https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
            "e082f7abefacd68fa56c1003bce3e60d82da7427/"
            "remote-development/tasks/p0-decoder-34-resume-checkpoint.json")
TASK_SHA256 = "51b7cd43373cb922d72f930e26b30f3a4b2630e2c6a9d9cb97089982e85b5138"
STAGE = "platform"


def report(state, detail):
    print(json.dumps({"stage": STAGE, "state": state, "detail": detail}, sort_keys=True))


def main():
    global STAGE
    if sys.platform != "darwin":
        raise RuntimeError("mac_only")
    home = Path.home().resolve()
    bridge = home / "Library/Application Support/RapBrainRemoteBridge"
    STAGE = "public_task"
    with urllib.request.urlopen(TASK_URL, timeout=20) as response:
        raw = response.read(4097)
        if response.geturl() != TASK_URL or len(raw) > 4096:
            raise RuntimeError("task_changed")
    if hashlib.sha256(raw).hexdigest() != TASK_SHA256:
        raise RuntimeError("task_hash_changed")
    task = json.loads(raw)
    STAGE = "signer_import"
    sys.path.insert(0, str(bridge))
    import mac_manager_sign_request as signer
    grant = signer.parse_sign_task(task, allow_expired=True)
    archive = signer.authorize(task, grant)
    with tempfile.TemporaryDirectory(prefix="rapbrain-sign-preflight-") as directory:
        root = Path(directory).resolve()
        STAGE = "verified_helper"
        modules, members = signer.verified_helpers(home, root)
        sys.path.insert(0, str(modules))
        from manager_update_release import verify_archive, verify_baseline, verify_manifest
        STAGE = "stable_manifest"
        stable = verify_manifest(signer.get_pinned(signer.CHANNEL, grant["stable_manifest_sha256"]))
        accepted = signer.read_remote_json(home / signer.STATE / "manager-accepted.json")
        if stable["sequence"] != 33 or accepted != {"sequence": 33}:
            raise RuntimeError("installed_sequence_changed")
        STAGE = "manager_launcher_and_dashboard"
        resources = home / signer.APP / "Contents/Resources"
        launcher = signer.checked(resources / "launch_manager.py", 250_000)
        dashboard = signer.checked(resources / "dashboard_beta14.html", 250_000)
        if (signer.sha(launcher) != signer.LAUNCHER
                or signer.sha(dashboard) != grant["baseline_dashboard_sha256"]):
            raise RuntimeError("manager_baseline_changed")
        STAGE = "release_baseline"
        manifest = {
            "schema": "rapbrain-manager-production-v1",
            "sequence": grant["sequence"],
            "issued_at": grant["issued_at"],
            "expires_at": grant["issued_at"] + 14 * 86400,
            "production_install_authorized": True,
            "data_migrations": [],
            "validation": signer.VALIDATION,
            "files": [{"path": "server.py",
                       "baseline_sha256": grant["expected_server_sha256"],
                       "payload_sha256": grant["candidate_server_sha256"]}],
            "required_server_sha256": grant["expected_server_sha256"],
            "archive_url": signer.REPO + "main/manager-stable/update-34.zip",
            "archive_sha256": grant["archive_sha256"],
            "archive_bytes": len(archive),
        }
        verify_baseline(manifest, home / signer.SOURCE, resources)
        STAGE = "release_archive"
        payload = verify_archive(archive, manifest)["server.py"]
        if hashlib.sha256(payload).hexdigest() != grant["candidate_server_sha256"]:
            raise RuntimeError("candidate_changed")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as output:
            for name, content in members.items():
                output.writestr("helper/" + name, content, compress_type=zipfile.ZIP_DEFLATED)
        STAGE = "prepare_trial"
        preparer, runner, support, button = signer.prepare_trial(root, buffer.getvalue(),
                                                                   grant["sequence"], decoder=True)
        publisher = signer.load(root / "publisher_signer.py",
                                signer.get_pinned(preparer.SIGNER, preparer.SIGNER_SHA))
        STAGE = "ephemeral_signature"
        public, signature = support.sign_ephemeral(publisher.canonical(manifest), root)
        public_trial = public
        trial = signer.envelope(manifest, public, signature, publisher.canonical)
        verify_manifest(trial, pinned_key=signer.sha(public))
        STAGE = "publisher_signature"
        public, signature = publisher.sign(home / signer.KEY, publisher.canonical(manifest))
        signed = signer.envelope(manifest, public, signature, publisher.canonical)
        verify_manifest(signed, minimum_sequence=stable["sequence"])
        STAGE = "signed_copy_rehearsal"
        support.LAUNCHER_SHA = signer.LAUNCHER
        support.DASHBOARD_SHA = grant["baseline_dashboard_sha256"]
        support.SERVER_SHA = grant["expected_server_sha256"]
        support.RUNTIME_SOURCES["server.py"] = grant["expected_server_sha256"]
        def trial_release(copy_dashboard, _branch):
            if copy_dashboard != dashboard:
                raise RuntimeError("copy_dashboard_changed")
            return trial, archive, payload, signer.sha(public_trial)
        support.signed_trial = trial_release
        try:
            proof = runner.run_trial(home, root / "remote", support, buffer.getvalue(), None, None,
                                     lambda port: button.request_update(port, runner, support))
        except Exception as error:
            for branch in ("committed", "rolled_back"):
                manager_log = root / "remote" / branch / "manager.log"
                if manager_log.is_file():
                    lines = manager_log.read_text(errors="replace").splitlines()[-18:]
                    print(json.dumps({"branch": branch, "manager_log_tail":
                                      [re.sub(r"/Users/[^/ ]+", "/Users/USER", line)[:250]
                                       for line in lines]}, sort_keys=True))
                detail_file = root / "remote" / branch / "home" / signer.STATE / "trial-error.json"
                if detail_file.is_file():
                    print(json.dumps({"branch": branch, "trial_error":
                                      detail_file.read_text(errors="replace")[:1500]}, sort_keys=True))
            raise
        if proof.get("copy_install") != "committed" or proof.get("copy_rollback") != "rolled_back":
            raise RuntimeError("signed_copy_proof_invalid")
    STAGE = "signed_copy_rehearsal_verified"
    report("pass", "copy_install_and_rollback_verified_unpublished")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        reason = str(error).replace("\n", " ")[:120]
        if not re.fullmatch(r"[A-Za-z0-9_ .:/-]{1,120}", reason):
            reason = type(error).__name__
        frames = [Path(frame.filename).name + ":" + str(frame.lineno) + ":" + frame.name
                  for frame in traceback.extract_tb(error.__traceback__)[-6:]]
        print(json.dumps({"stage": STAGE, "state": "refused", "detail": reason,
                          "error_type": type(error).__name__, "functions": frames}, sort_keys=True))
