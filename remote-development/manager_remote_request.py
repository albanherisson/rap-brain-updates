"""Private local request format shared by the Mac bridge and Manager launcher."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time


REMOTE_REQUEST_SCHEMA = "rapbrain-manager-install-v1"
REMOTE_FIELDS = frozenset(("schema", "id", "sequence", "manifest_sha256",
                           "expected_server_sha256", "expires_at"))
REMOTE_TERMINAL = frozenset(("committed", "rolled_back", "aborted", "restored_stopped",
                             "check_required", "refused", "up_to_date", "expired"))


def remote_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_remote_request(request, now=None, *, allow_expired=False):
    current = time.time() if now is None else now
    if (type(request) is not dict or request.keys() != REMOTE_FIELDS
            or request["schema"] != REMOTE_REQUEST_SCHEMA
            or type(request["id"]) is not str
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", request["id"])
            or type(request["sequence"]) is not int or request["sequence"] < 1
            or any(type(request[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", request[key])
                   for key in ("manifest_sha256", "expected_server_sha256"))
            or type(request["expires_at"]) is not int
            or request["expires_at"] > current + 7 * 86400
            or (not allow_expired and current >= request["expires_at"])):
        raise ValueError("invalid_remote_manager_request")
    return request


def remote_directory(home, *, create=False):
    directory = Path(home) / "Library/Application Support/RapBrainRemoteBridge/manager-updates"
    if any(path.is_symlink() for path in (directory, *directory.parents)):
        raise ValueError("unsafe_remote_manager_directory")
    if create:
        directory.mkdir(mode=0o700, exist_ok=True)
    try:
        info = directory.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("unsafe_remote_manager_directory")
    return directory


def read_remote_json(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or not 0 < info.st_size <= 4096):
            raise ValueError("unsafe_remote_manager_record")
        raw = stream.read(4097)
    if len(raw) != info.st_size:
        raise ValueError("unsafe_remote_manager_record")
    return decode_remote_json(raw)


def decode_remote_json(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= 4096:
        raise ValueError("invalid_remote_manager_record")
    def unique(pairs):
        output = {}
        for key, value in pairs:
            if key in output:
                raise ValueError("duplicate_remote_manager_field")
            output[key] = value
        return output

    return json.loads(raw, object_pairs_hook=unique)


def lock_remote_directory(directory):
    fd = os.open(directory / "manager.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("unsafe_remote_manager_lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


def write_remote_json(path, value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".manager-update-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def remote_receipt(directory, request):
    record = read_remote_json(directory / (request["id"] + ".json"))
    if record is not None and (
            type(record) is not dict or record.get("request_sha256") != remote_digest(request)):
        raise ValueError("remote_manager_receipt_mismatch")
    return record


def save_remote_receipt(directory, request, state, *, attempt=None, reason=None, manager_reopened=None):
    record = {"request_sha256": remote_digest(request), "state": state}
    if attempt is not None:
        if type(attempt) is not str or not re.fullmatch(r"[0-9a-f]{32}", attempt):
            raise ValueError("invalid_remote_manager_attempt")
        record["attempt"] = attempt
    if type(reason) is str and re.fullmatch(r"[a-zA-Z0-9_]{1,80}", reason):
        record["reason"] = reason
    if type(manager_reopened) is bool:
        record["manager_reopened"] = manager_reopened
    write_remote_json(directory / (request["id"] + ".json"), record)
    return record


def queue_remote_request(directory, request):
    validate_remote_request(request)
    path = directory / "request.json"
    previous = read_remote_json(path)
    if previous == request:
        return
    if previous is not None:
        validate_remote_request(previous, allow_expired=True)
        receipt = remote_receipt(directory, previous)
        if not receipt or receipt["state"] not in REMOTE_TERMINAL:
            raise ValueError("remote_manager_request_already_pending")
    write_remote_json(path, request)
