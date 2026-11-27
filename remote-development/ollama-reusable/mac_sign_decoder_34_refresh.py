#!/usr/bin/env python3
"""Renew the narrow reviewed grant at launch and sign Decoder 34 on Python 3.10+."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

TASK_ID = "p0-decoder-34-resume-checkpoint"
PRIVATE_BRANCH = "p0/decoder-resume-signing-34"
PRIVATE_PATH = "remote-development/manager-signing/" + TASK_ID + "/authorization.json"
PUBLIC_BRANCH = "p0/remote-development-preflight"
EXPECTED = {
    "id": TASK_ID,
    "sequence": 34,
    "archive_sha256": "c1cdf54b2b39591c3ab4e9066c67f6499bb59203dd7c06d8dfa71b89e4c8492d",
    "baseline_dashboard_sha256": "dce7d8f87cc76b81dbf9cb0af5bfad59041748ede14d037436617888f630ca41",
    "stable_manifest_sha256": "818a65304f611ac55c51f7a057036f7fcf5deacc3aae10d00dd4335110d0ac34",
    "expected_server_sha256": "c24abf6a8da3614cb29143c4d6fe5a50c82917c8e947d5e58c08606f59de986c",
    "candidate_server_sha256": "c26fe011c22b7d6bcb3c6e8853cee7f5e976b49f8c4908f47637d7b121893804",
    "source_manifest_sha256": "27e63a5378b60373ad899dfb44894251a22a9a11d3447b5a151a303caa7bd014",
    "decoder_test_sha256": "f83a0bf1d34e950e8b7bec7bf47ceb5661fc59f358752f74ccc2e4b8a17e5c43",
}


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


def file_on_branch(bridge, url, token):
    item = bridge.request(url, token=token)
    if (type(item) is not dict or item.get("type") != "file"
            or item.get("encoding") != "base64" or type(item.get("sha")) is not str
            or not re.fullmatch(r"[0-9a-f]{40}", item["sha"])):
        raise RuntimeError("signing_source_missing")
    raw = base64.b64decode(item["content"].replace("\n", ""), validate=True)
    if len(raw) != item["size"] or len(raw) > 4096:
        raise RuntimeError("signing_source_size_changed")
    return item["sha"], json.loads(raw)


def check_grant(grant):
    if (type(grant) is not dict or grant.keys() != EXPECTED.keys() | {"schema", "issued_at", "expires_at"}
            or grant["schema"] != "rapbrain-manager-sign-reviewed-decoder-v1"
            or any(type(grant[k]) is not type(v) or grant[k] != v for k, v in EXPECTED.items())
            or type(grant["issued_at"]) is not int or type(grant["expires_at"]) is not int):
        raise RuntimeError("reviewed_grant_changed")


def check_task(task, grant):
    expected = {k: v for k, v in grant.items() if k != "schema"}
    if (type(task) is not dict or task.keys() != expected.keys() | {"schema", "action", "authorization_commit"}
            or task["schema"] != "rapbrain-remote-task-v4"
            or task["action"] != "manager_sign_reviewed_decoder"
            or any(type(task[k]) is not type(v) or task[k] != v for k, v in expected.items())
            or type(task["authorization_commit"]) is not str
            or not re.fullmatch(r"[0-9a-f]{40}", task["authorization_commit"])):
        raise RuntimeError("reviewed_task_changed")


def update_file(bridge, url, branch, blob, body, token, message):
    content = json.dumps(body, separators=(",", ":")).encode()
    request = json.dumps({"message": message, "content": base64.b64encode(content).decode(),
                          "sha": blob, "branch": branch}).encode()
    response = bridge.request(url.split("?", 1)[0], method="PUT", token=token, payload=request)
    commit = response.get("commit", {}).get("sha") if type(response) is dict else None
    if type(commit) is not str or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("signing_refresh_unconfirmed")
    return commit


def main():
    if sys.platform != "darwin":
        raise RuntimeError("mac_only")
    choose_python()
    home = Path.home().resolve()
    bridge_path = home / "Library/Application Support/RapBrainRemoteBridge"
    if bridge_path.is_symlink() or not bridge_path.is_dir():
        raise RuntimeError("bridge_directory_invalid")
    sys.path.insert(0, str(bridge_path))
    import mac_bridge as bridge
    token = bridge.keychain_token()
    try:
        private_url = ("https://api.github.com/repos/albanherisson/rap-brain-source/contents/"
                       + PRIVATE_PATH + "?ref=" + bridge.urllib.parse.quote(PRIVATE_BRANCH, safe=""))
        public_url = bridge.contents_url("tasks", TASK_ID)
        private_blob, grant = file_on_branch(bridge, private_url, token)
        public_blob, task = file_on_branch(bridge, public_url, token)
        check_grant(grant)
        check_task(task, grant)
        current = int(time.time())
        if task["expires_at"] < current + 2400:
            grant["issued_at"] = current - 5
            grant["expires_at"] = grant["issued_at"] + 3600
            commit = update_file(bridge, private_url, PRIVATE_BRANCH, private_blob, grant, token,
                                 "Renew reviewed Decoder 34 signing at Mac launch")
            task.update({"issued_at": grant["issued_at"], "expires_at": grant["expires_at"],
                         "authorization_commit": commit})
            update_file(bridge, public_url, PUBLIC_BRANCH, public_blob, task, token,
                        "Renew Decoder 34 signing task at Mac launch")
        else:
            if not current < task["expires_at"]:
                raise RuntimeError("signing_task_expired")
        task, task_hash = bridge.read_task(TASK_ID)
        check_task(task, grant)
        result = bridge.run(task, task_hash)
        if result["status"] == "pending":
            raise RuntimeError("signing_pending")
        result_id = "p0-decoder-34-signing-" + str(int(time.time()))
        bridge.publish(result_id, result, token)
        signing = result.get("manager_sign", {})
        print(json.dumps({"stage": "reviewed_signing_result_published",
                          "state": result["status"], "reason": signing.get("reason"),
                          "manifest_sha256": signing.get("manifest_sha256"),
                          "result": result_id}, sort_keys=True))
    finally:
        token = ""


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        reason = str(error)
        print(json.dumps({"stage": "reviewed_signing", "state": "refused",
                          "reason": reason if re.fullmatch(r"[a-zA-Z0-9_ .]{1,80}", reason)
                          else type(error).__name__}, sort_keys=True))
