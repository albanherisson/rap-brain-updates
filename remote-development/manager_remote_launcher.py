"""Manager-side dispatch through its existing signed-update handoff."""

import hashlib
import http.client
import os
from pathlib import Path
import sys
import time


REMOTE_MANAGER_PORT = 8765


def inspect_remote_release(request, rap_dir, backup_dir):
    from manager_helper_release import verify_staged

    secure = backup_dir / "secure-update"
    helper = verify_staged(secure)
    sys.path.insert(0, str(helper))
    from manager_update_release import CHANNEL, fetch, verify_baseline, verify_manifest
    from pending_attempt_recovery import _private_json

    signed = fetch(CHANNEL, 65536)
    if hashlib.sha256(signed).hexdigest() != request["manifest_sha256"]:
        raise ValueError("remote_manager_manifest_changed")
    manifest = verify_manifest(signed)
    if (manifest["sequence"] != request["sequence"]
            or manifest["required_server_sha256"] != request["expected_server_sha256"]
            or hashlib.sha256((rap_dir / "server.py").read_bytes()).hexdigest()
            != request["expected_server_sha256"]):
        raise ValueError("remote_manager_release_mismatch")
    receipt = secure / "manager-accepted.json"
    if receipt.exists():
        accepted = _private_json(receipt, 256)
        if type(accepted) is not dict or type(accepted.get("sequence")) is not int:
            raise ValueError("manager_accepted_record_invalid")
        if accepted["sequence"] >= request["sequence"]:
            return None
    stable = (Path.home() / "Downloads/RapBrainManager_App_Beta14" /
              "Rap Brain Manager Beta 14.app/Contents/Resources/launch_manager.py")
    if (stable.is_symlink() or hashlib.sha256(stable.read_bytes()).digest()
            != hashlib.sha256(Path(__file__).resolve().read_bytes()).digest()):
        raise ValueError("stable_manager_app_changed")
    verify_baseline(manifest, rap_dir, stable.parent)
    return signed, manifest


def remote_update_step(root, rap_dir, backup_dir, supervisor, directory, request):
    receipt = remote_receipt(directory, request)
    stage = receipt["state"] if receipt else None
    if stage in REMOTE_TERMINAL or stage in ("dispatching", "handoff"):
        return False
    if time.time() >= request["expires_at"]:
        save_remote_receipt(directory, request, "expired")
        return False
    ticket = remote_digest(request)
    if supervisor.get("remote_update_ticket") != ticket:
        release = inspect_remote_release(request, rap_dir, backup_dir)
        if release is None:
            save_remote_receipt(directory, request, "up_to_date")
            return False
        supervisor["remote_update_ticket"] = ticket
        supervisor["remote_update_release"] = release

    handle = supervisor.get("process")
    if handle is None or handle.poll() is not None:
        if supervisor.get("remote_update_start") == ticket:
            raise ValueError("remote_manager_server_start_failed")
        if port_in_use():
            if stage != "waiting_foreign_server":
                save_remote_receipt(directory, request, "waiting_foreign_server")
            return False
        if not (root / "launch-request.json").exists():
            write_remote_json(root / "launch-request.json", {"action": "start", "script": "server.py"})
        supervisor["remote_update_start"] = ticket
        save_remote_receipt(directory, request, "starting_server")
        return False

    from authenticated_runtime_client import read_runtime_proof
    from creative_release import Refused
    from owned_supervisor_binding import bind_owned_launch

    owned = bind_owned_launch(supervisor, expected_server_sha256=request["expected_server_sha256"])
    try:
        read_runtime_proof(REMOTE_MANAGER_PORT, owned.token, expected_parent_pid=owned.handle.pid)
    except Refused as exc:
        if str(exc) not in ("runtime_process_identity_mismatch", "runtime_proof_unavailable",
                            "listener_identity_unavailable"):
            raise
        return False
    return handle_manager_update_request(root, rap_dir, backup_dir, supervisor,
                                         remote=(directory, request, *supervisor["remote_update_release"]))


def handle_remote_manager_update(root, rap_dir, backup_dir, supervisor):
    # This loop shares the Manager's retained server handle and cannot adopt a PID.
    now = time.monotonic()
    if now < supervisor.get("remote_update_poll_after", 0):
        return False
    supervisor["remote_update_poll_after"] = now + 1
    try:
        directory = remote_directory(Path.home())
        if directory is None:
            return False
        request = read_remote_json(directory / "request.json")
        if request is None:
            return False
        validate_remote_request(request, allow_expired=True)
        try:
            fd = lock_remote_directory(directory)
        except BlockingIOError:
            return False
        try:
            try:
                return remote_update_step(root, rap_dir, backup_dir, supervisor, directory, request)
            except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
                save_remote_receipt(directory, request, "refused", reason=str(exc))
        finally:
            os.close(fd)
    except (OSError, ValueError, RuntimeError):
        # An unavailable or malformed mailbox cannot prevent a manual update.
        return False
    return False
