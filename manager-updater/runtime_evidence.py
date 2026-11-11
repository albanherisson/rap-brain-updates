"""Collect a fail-closed, read-only shutdown boundary for a Manager-owned child.

The caller must have established its own durable maintenance attempt and keep
the marker until the transaction is terminal. This module never sends signals.
"""
import fcntl
import hashlib
import os
import sqlite3
import sys

from authenticated_runtime_client import read_runtime_proof
from creative_release import Refused
from creative_shutdown_policy import RuntimeProof, assert_safe_to_stop
from creative_transaction import safe_path
from process_group_inventory import read_owned_group
from process_start_identity import read_start, require_live_owned_handle
from worker_activity_gate import _lock, _state


def collect_owned_idle_proof(*, source, state, handle, recorded_start,
                             recorded_server_sha256, token, ticket, port):
    """Bind the retained child, authenticated server and fresh OS snapshot.

    Locks are acquired after the durable marker exists. Their exclusive hold
    proves all earlier HTTP requests and worker jobs drained; the marker keeps
    later writes excluded after the locks are released. The caller must repeat
    this collection immediately before any future signal.
    """
    source = safe_path(source, directory=True)
    state = _state(state)
    script = safe_path(source / 'server.py')
    if (type(recorded_server_sha256) is not str or
            len(recorded_server_sha256) != 64 or
            any(c not in '0123456789abcdef' for c in recorded_server_sha256) or
            hashlib.sha256(script.read_bytes()).hexdigest() != recorded_server_sha256):
        raise Refused('server_script_identity_changed')
    if (type(ticket) is not bytes or len(ticket) != 65 or
            ticket[-1:] != b'\n' or
            any(c not in b'0123456789abcdef' for c in ticket[:-1])):
        raise Refused('maintenance_ticket_invalid')
    if (type(getattr(handle, 'args', None)) not in (list, tuple) or
            len(handle.args) != 3 or handle.args[0] != sys.executable or
            handle.args[1] != '-u' or
            os.path.realpath(handle.args[2]) != str(script.resolve())):
        raise Refused('owned_launch_script_mismatch')

    parent_start = require_live_owned_handle(handle, recorded_start)
    admission = _lock(state, 'admission.lock', fcntl.LOCK_EX)
    try:
        job = _lock(state, 'worker-job.lock', fcntl.LOCK_EX)
        try:
            marker = safe_path(state / 'maintenance.ticket')
            if (marker.stat().st_uid != os.getuid() or
                    marker.stat().st_mode & 0o077 or
                    marker.read_bytes() != ticket):
                raise Refused('maintenance_ticket_mismatch')
            report = read_runtime_proof(port, token, expected_parent_pid=handle.pid)
            group = read_owned_group(manager_pid=os.getpid(), parent_pid=handle.pid,
                                     worker_pid=report['worker_pid'])
            worker_start = read_start(report['worker_pid'])
            db = safe_path(source / 'data' / 'rapbrain.sqlite3')
            con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5)
            try:
                con.execute('PRAGMA query_only=ON')
                rows = con.execute('SELECT status, COUNT(*) FROM jobs GROUP BY status').fetchall()
            finally:
                con.close()
            if any(type(k) is not str or type(v) is not int for k, v in rows):
                raise Refused('jobs_active_or_unknown_status')
            counts = dict(rows)
            proof = RuntimeProof(
                parent_pid=handle.pid, worker_pid=report['worker_pid'],
                parent_start_token=parent_start, worker_start_token=worker_start,
                parent_script_sha256=recorded_server_sha256,
                worker_script_sha256=recorded_server_sha256,
                audio_pid=report['audio_pid'], process_group_pids=group,
                authenticated_parent=True, parent_owned_handle_alive=True,
                worker_same_script=report['worker_script_matches'],
                worker_idle_verified=True, audio_idle_verified=True,
                admission_marker_held=True, http_requests_drained=True,
                job_status_counts=counts)
            assert_safe_to_stop(proof, owned_pid=handle.pid,
                                owned_start_token=recorded_start,
                                expected_server_sha256=recorded_server_sha256)
            # A health response could have raced with child exit during the OS
            # snapshot. Verify the retained handle again while locks are held.
            require_live_owned_handle(handle, recorded_start)
            return proof
        finally:
            os.close(job)
    finally:
        os.close(admission)
