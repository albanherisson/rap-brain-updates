"""Read-only recovery boundary for a stopped, ticketed guarded server.

The returned exclusive lifetime lock must be retained until the same ticket
starts a candidate. A future Manager lifecycle also has to verify the local
listener is absent and implement authenticated candidate health. This module
does not restart processes, remove markers, or edit application/data files.
"""
import fcntl
import hashlib
import json
import os
import stat
from pathlib import Path

from creative_release import Refused
from creative_transaction import safe_path
from worker_activity_gate import _lock, _state


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Refused('duplicate_recovery_field')
        value[key] = item
    return value


def _private_json(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077 or not 0 < info.st_size <= maximum):
            raise Refused('unsafe_recovery_record')
        raw = os.read(fd, maximum + 1)
    finally:
        os.close(fd)
    try:
        return json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, UnicodeError) as exc:
        raise Refused('invalid_recovery_record') from exc


class PendingAttempt:
    def __init__(self, fd, ticket, identifier):
        self.fd = fd
        self.ticket = ticket
        self.transaction_id = identifier

    def assert_stopped(self):
        if self.fd is None:
            raise Refused('recovery_lifetime_lock_released')

    def release_to_ticketed_candidate(self):
        self.assert_stopped()
        os.close(self.fd)
        self.fd = None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def acquire_stopped_attempt(source, state, identifier, *, listener_absent):
    """Resume only the original pending attempt while both writers are gone.

    listener_absent is a mandatory, independently verified local-port census
    supplied by the future macOS lifecycle. The exclusive lifetime lock proves
    absence of guarded HTTP parent and worker, including after Manager exit.
    """
    source = safe_path(source, directory=True)
    state = _state(state)
    if (type(identifier) is not str or len(identifier) != 32 or
            any(c not in '0123456789abcdef' for c in identifier) or
            not callable(listener_absent)):
        raise Refused('invalid_recovery_request')
    fd = os.open(state / 'update.lock', os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077):
            raise Refused('unsafe_lifetime_lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refused('guarded_writers_still_running') from exc
        admission = _lock(state, 'admission.lock', fcntl.LOCK_EX)
        try:
            job = _lock(state, 'worker-job.lock', fcntl.LOCK_EX)
            try:
                intent = _private_json(state / 'maintenance-intent.json', 4096)
                journal = _private_json(state / 'transaction.json', 65536)
                ticket_path = state / 'maintenance.ticket'
                marker = os.open(ticket_path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    marker_info = os.fstat(marker)
                    if (not stat.S_ISREG(marker_info.st_mode) or
                            marker_info.st_uid != os.getuid() or
                            marker_info.st_mode & 0o077):
                        raise Refused('unsafe_recovery_ticket')
                    ticket = os.read(marker, 66)
                finally:
                    os.close(marker)
                if (type(ticket) is not bytes or len(ticket) != 65 or
                        ticket[-1:] != b'\n' or
                        any(c not in b'0123456789abcdef' for c in ticket[:-1]) or
                        type(intent) is not dict or
                        intent.get('schema') != 'rapbrain-prejournal-intent-v1' or
                        intent.get('source') != str(source) or
                        intent.get('id') != identifier or
                        intent.get('ticket_sha256') != hashlib.sha256(ticket).hexdigest() or
                        intent.get('server_sha256') != hashlib.sha256(
                            safe_path(source / 'server.py').read_bytes()).hexdigest() or
                        type(journal) is not dict or journal.get('id') != identifier or
                        journal.get('source') != str(source) or
                        journal.get('phase') not in
                        ('preparing', 'backup_ready', 'switch_pending', 'switched',
                         'rollback_pending')):
                    raise Refused('recovery_attempt_mismatch')
                if listener_absent() is not True:
                    raise Refused('local_listener_still_present_or_unknown')
                return PendingAttempt(fd, ticket, identifier)
            finally:
                os.close(job)
        finally:
            os.close(admission)
    except BaseException:
        os.close(fd)
        raise
