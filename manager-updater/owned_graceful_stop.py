"""Gracefully stop only a proven Manager-owned, idle guarded server.

No PID signal, port discovery or fallback kill is allowed. On any uncertainty
the durable maintenance marker remains and no code replacement is authorized.
The returned lifetime lock must remain held until the ticketed candidate starts.
This is not wired to the Beta 14 application.
"""
import fcntl
import http.client
import json
import os
import stat
import subprocess

from authenticated_runtime_client import assert_owned_listener
from creative_release import Refused
from process_group_inventory import parse_ps
from runtime_evidence import collect_owned_idle_proof
from worker_activity_gate import _state


class StoppedLease:
    def __init__(self, fd, parent_pid, worker_pid):
        self.fd = fd
        self.parent_pid = parent_pid
        self.worker_pid = worker_pid

    def release_to_ticketed_candidate(self):
        """Caller retains the marker/ticket throughout the restart handoff."""
        if self.fd is None:
            raise Refused('lifetime_lock_already_released')
        os.close(self.fd)
        self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _stop_response(raw):
    if type(raw) is not bytes or len(raw) > 128:
        raise Refused('stop_response_invalid')
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise Refused('stop_response_duplicate')
            out[key] = value
        return out
    try:
        result = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise Refused('stop_response_invalid') from exc
    if type(result) is not dict or result != {'stopping': True}:
        raise Refused('stop_response_invalid')


def _assert_group_gone(parent_pid, worker_pid):
    try:
        result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid='],
                                capture_output=True, text=True, timeout=5,
                                stdin=subprocess.DEVNULL, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('post_stop_inventory_unavailable') from exc
    if result.stderr:
        raise Refused('post_stop_inventory_unexpected_output')
    members = parse_ps(result.stdout)
    if (parent_pid in members or worker_pid in members or
            any(member.pgid == parent_pid for member in members.values())):
        raise Refused('server_group_not_stopped')


def graceful_stop_owned(*, source, state, handle, recorded_start,
                        recorded_server_sha256, token, ticket, port):
    proof = collect_owned_idle_proof(
        source=source, state=state, handle=handle, recorded_start=recorded_start,
        recorded_server_sha256=recorded_server_sha256, token=token,
        ticket=ticket, port=port)
    # The collection rechecked the retained handle, OS parentage, marker,
    # worker lock, jobs and audio. Verify the listener before sending secrets.
    assert_owned_listener(port, handle.pid)
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request('POST', '/api/manager-update-stop',
                           headers={'X-RB-Update-Token': token,
                                    'X-RB-Update-Ticket': ticket[:-1].decode('ascii')},
                           body=b'')
        response = connection.getresponse()
        if (response.status != 202 or
                response.getheader('Content-Type', '').split(';')[0] != 'application/json'):
            raise Refused('graceful_stop_refused')
        _stop_response(response.read(129))
    except (OSError, http.client.HTTPException) as exc:
        raise Refused('graceful_stop_unavailable') from exc
    finally:
        connection.close()
    try:
        handle.wait(timeout=12)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused('owned_server_did_not_exit') from exc
    if handle.poll() is None:
        raise Refused('owned_server_did_not_exit')
    _assert_group_gone(proof.parent_pid, proof.worker_pid)
    directory = _state(state)
    fd = os.open(directory / 'update.lock', os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077):
            raise Refused('unsafe_lifetime_lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refused('server_lifetime_still_active') from exc
        # Marker still excludes unrelated launches while this lock is released
        # for the exact ticketed candidate. Only the caller may release it.
        marker = directory / 'maintenance.ticket'
        if marker.is_symlink() or marker.read_bytes() != ticket:
            raise Refused('maintenance_ticket_changed')
        return StoppedLease(fd, proof.parent_pid, proof.worker_pid)
    except BaseException:
        os.close(fd)
        raise
