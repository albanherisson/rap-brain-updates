"""Prove the requesting Manager parent exited before an external update.

The helper inherits only a pipe read descriptor. The parent writes a fresh
nonce and keeps the write descriptor until it exits. A closed pipe alone is
insufficient; the exact process start identity is rechecked with ps. This
module never stops or signals a process and never opens Rap Brain data.
"""
import hashlib
import os
import re
import select
import stat
import subprocess
import time

from creative_release import Refused
from process_start_identity import parse_start


HEX = re.compile(r'[0-9a-f]{64}\Z')


def parent_has_exited(pid, recorded_start):
    if type(pid) is not int or pid < 2 or type(recorded_start) is not str:
        raise Refused('manager_parent_identity_invalid')
    try:
        result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart='],
                                capture_output=True, text=True, timeout=5,
                                stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('manager_parent_inventory_unavailable') from exc
    if result.stderr:
        raise Refused('manager_parent_inventory_unexpected')
    if result.returncode == 1 and not result.stdout.strip():
        return True
    if result.returncode != 0:
        raise Refused('manager_parent_inventory_unavailable')
    return parse_start(result.stdout, pid) != recorded_start


def wait_for_parent_exit(read_fd, nonce_sha256, parent_pid, parent_start,
                         *, timeout=20):
    if (type(read_fd) is not int or read_fd < 3 or
            type(nonce_sha256) is not str or not HEX.fullmatch(nonce_sha256) or
            type(timeout) not in (int, float) or not 0 < timeout <= 30):
        raise Refused('manager_handoff_proof_invalid')
    info = os.fstat(read_fd)
    if not stat.S_ISFIFO(info.st_mode):
        raise Refused('manager_handoff_pipe_required')
    deadline = time.monotonic() + timeout
    try:
        received = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Refused('manager_handoff_timeout')
            readable, _, _ = select.select([read_fd], [], [], remaining)
            if not readable:
                raise Refused('manager_handoff_timeout')
            chunk = os.read(read_fd, 34 - len(received))
            if not chunk:
                break
            received.extend(chunk)
            if len(received) > 32:
                raise Refused('manager_handoff_nonce_size')
        if (len(received) != 32 or
                hashlib.sha256(received).hexdigest() != nonce_sha256):
            raise Refused('manager_handoff_nonce_changed')
    finally:
        os.close(read_fd)
    while time.monotonic() < deadline:
        if parent_has_exited(parent_pid, parent_start):
            return True
        time.sleep(0.05)
    raise Refused('manager_parent_still_running')
