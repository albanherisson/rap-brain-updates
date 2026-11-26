#!/usr/bin/env python3
"""Read-only diagnosis of the already refused Decoder 34 signing request."""

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.request


TASK_URL = ("https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
            "e082f7abefacd68fa56c1003bce3e60d82da7427/"
            "remote-development/tasks/p0-decoder-34-resume-checkpoint.json")
TASK_SHA256 = "51b7cd43373cb922d72f930e26b30f3a4b2630e2c6a9d9cb97089982e85b5138"
BRIDGE = Path.home() / "Library/Application Support/RapBrainRemoteBridge"
SERVER = Path.home() / "Downloads/rap-brain/server.py"
STAGE = "platform"


def report(state, detail):
    print(json.dumps({"stage": STAGE, "state": state, "detail": detail}, sort_keys=True))


def main():
    global STAGE
    if sys.platform != "darwin" or not BRIDGE.is_dir():
        raise RuntimeError("mac_bridge_unavailable")
    STAGE = "public_task"
    with urllib.request.urlopen(TASK_URL, timeout=20) as response:
        raw = response.read(4097)
        if response.geturl() != TASK_URL or len(raw) > 4096:
            raise RuntimeError("public_task_changed")
    if hashlib.sha256(raw).hexdigest() != TASK_SHA256:
        raise RuntimeError("public_task_hash_changed")
    task = json.loads(raw)
    STAGE = "signer_import"
    sys.path.insert(0, str(BRIDGE))
    import mac_manager_sign_request as signer
    STAGE = "signer_parse"
    grant = signer.parse_sign_task(task, allow_expired=True)
    STAGE = "private_authorization_and_archive"
    archive = signer.authorize(task, grant)
    if not isinstance(archive, bytes) or hashlib.sha256(archive).hexdigest() != task["archive_sha256"]:
        raise RuntimeError("archive_changed")
    STAGE = "local_baseline"
    if hashlib.sha256(SERVER.read_bytes()).hexdigest() != task["expected_server_sha256"]:
        raise RuntimeError("installed_server_changed")
    STAGE = "signed_channel"
    signed = signer.get_pinned(signer.CHANNEL, grant["stable_manifest_sha256"])
    if not signed:
        raise RuntimeError("signed_channel_empty")
    STAGE = "verified_helper"
    with tempfile.TemporaryDirectory(prefix="rapbrain-sign-diagnosis-") as temporary:
        signer.verified_helpers(Path.home().resolve(), Path(temporary).resolve())
    STAGE = "preflight_complete"
    report("pass", "authorization_archive_baseline_channel_helper_verified")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        reason = str(error).replace("\n", " ")[:120]
        if not re.fullmatch(r"[A-Za-z0-9_ .:/-]{1,120}", reason):
            reason = type(error).__name__
        report("refused", reason)
