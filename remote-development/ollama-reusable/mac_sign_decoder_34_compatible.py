#!/usr/bin/env python3
"""Run the reviewed Decoder 34 signing request with a compatible Python runtime."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

TASK_ID = "p0-decoder-34-resume-checkpoint"
TASK_SHA256 = "da4d8abe8734b2657e1250bb6db5a7274507a52bd4ed213e43ff4db5d986007b"
AUTHORIZATION = "6b98c2ddb998a58ccf69bbbb6e447a706675c018"
RESULT_ID = "p0-decoder-34-compatible-signing"
CANDIDATE = "c26fe011c22b7d6bcb3c6e8853cee7f5e976b49f8c4908f47637d7b121893804"


def choose_python():
    if sys.version_info >= (3, 10):
        return
    candidates = [Path("/opt/homebrew/bin/python3"), Path("/usr/local/bin/python3")]
    for base in ("/opt/homebrew/bin", "/usr/local/bin",
                 "/Library/Frameworks/Python.framework/Versions/3.13/bin",
                 "/Library/Frameworks/Python.framework/Versions/3.12/bin",
                 "/Library/Frameworks/Python.framework/Versions/3.11/bin",
                 "/Library/Frameworks/Python.framework/Versions/3.10/bin"):
        candidates.extend(Path(base) / ("python3." + str(minor))
                          for minor in (13, 12, 11, 10))
    for interpreter in candidates:
        if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            continue
        probe = subprocess.run([str(interpreter), "-I", "-c",
                                "import sys; print(int(sys.version_info >= (3, 10)))"],
                               capture_output=True, text=True, timeout=8)
        if probe.returncode == 0 and probe.stdout.strip() == "1":
            os.execv(str(interpreter), [str(interpreter), "-I", "-B", str(Path(__file__).resolve())])
    raise RuntimeError("compatible_python_missing")


def main():
    if sys.platform != "darwin":
        raise RuntimeError("mac_only")
    choose_python()
    home = Path.home().resolve()
    bridge_path = home / "Library/Application Support/RapBrainRemoteBridge"
    if not bridge_path.is_dir() or bridge_path.is_symlink():
        raise RuntimeError("bridge_directory_invalid")
    sys.path.insert(0, str(bridge_path))
    import mac_bridge as bridge
    task, task_hash = bridge.read_task(TASK_ID)
    if (task_hash != TASK_SHA256 or task["id"] != TASK_ID or task["sequence"] != 34
            or task["action"] != "manager_sign_reviewed_decoder"
            or task["authorization_commit"] != AUTHORIZATION
            or task["candidate_server_sha256"] != CANDIDATE):
        raise RuntimeError("reviewed_signing_task_changed")
    result = bridge.run(task, task_hash)
    if result["status"] == "pending":
        raise RuntimeError("signing_pending")
    token = bridge.keychain_token()
    try:
        bridge.publish(RESULT_ID, result, token)
    finally:
        token = ""
    signing = result.get("manager_sign", {})
    print(json.dumps({"stage": "reviewed_signing_result_published",
                      "state": result["status"],
                      "reason": signing.get("reason"),
                      "manifest_sha256": signing.get("manifest_sha256"),
                      "result": RESULT_ID}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        reason = str(error)
        print(json.dumps({"stage": "reviewed_signing", "state": "refused",
                          "reason": reason if re.fullmatch(r"[a-zA-Z0-9_]{1,80}", reason)
                          else type(error).__name__}, sort_keys=True))
