"""Disposable worker/maintenance gate primitive; not installed in Rap Brain.

The worker holds a shared lock for the entire job. Maintenance takes that lock
exclusively before creating a durable marker. A worker checks the marker while
holding its shared lock, so no job can slip between the idle check and marker.
The caller must retain the marker until commit or rollback is terminal.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from creative_release import Refused


def _state(directory):
    directory = Path(directory).absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise Refused('unsafe_worker_gate_path')
    info = directory.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
            info.st_mode & 0o077):
        raise Refused('private_worker_gate_directory_required')
    return directory


def _lock(directory, name, operation):
    fd = os.open(directory / name,
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077):
            raise Refused('unsafe_worker_job_lock')
        try:
            fcntl.flock(fd, operation | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refused('worker_busy_or_maintenance') from exc
        return fd
    except BaseException:
        os.close(fd)
        raise


class JobLease:
    def __init__(self, directory):
        self.directory = directory
        self.fd = None

    def __enter__(self):
        directory = _state(self.directory)
        fd = _lock(directory, 'worker-job.lock', fcntl.LOCK_SH)
        if os.path.lexists(directory / 'maintenance.ticket'):
            os.close(fd)
            raise Refused('maintenance_in_progress')
        self.fd = fd
        return self

    def __exit__(self, *_):
        os.close(self.fd)
        self.fd = None


def begin_maintenance(directory, ticket):
    """Atomically establish exclusion; refuse an active job without waiting."""
    directory = _state(directory)
    if (type(ticket) is not bytes or len(ticket) != 65 or
            ticket[-1:] != b'\n' or
            any(c not in b'0123456789abcdef' for c in ticket[:-1])):
        raise Refused('invalid_maintenance_ticket')
    # HTTP requests hold admission.lock shared until their handler returns.
    # Taking it first prevents any new POST from racing with the marker.
    admission_fd = _lock(directory, 'admission.lock', fcntl.LOCK_EX)
    try:
        fd = _lock(directory, 'worker-job.lock', fcntl.LOCK_EX)
        try:
            path = directory / 'maintenance.ticket'
            marker = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(marker, 'wb') as stream:
                    stream.write(ticket)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                # A partial marker remains: recovery must fail closed.
                raise
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            os.close(fd)
    finally:
        os.close(admission_fd)


def finish_maintenance(directory, ticket, *, expected_transaction_id,
                       owned_health_verified, require_intent=False):
    """Release a marker only after a durable terminal journal and owned health."""
    directory = _state(directory)
    if owned_health_verified is not True:
        raise Refused('owned_health_not_verified')
    admission_fd = _lock(directory, 'admission.lock', fcntl.LOCK_EX)
    try:
        job_fd = _lock(directory, 'worker-job.lock', fcntl.LOCK_EX)
        try:
            marker_path = directory / 'maintenance.ticket'
            marker_fd = os.open(marker_path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                marker_info = os.fstat(marker_fd)
                if (not stat.S_ISREG(marker_info.st_mode) or
                        marker_info.st_uid != os.getuid() or marker_info.st_mode & 0o077 or
                        type(ticket) is not bytes or len(ticket) != 65 or
                        os.read(marker_fd, 66) != ticket):
                    raise Refused('maintenance_ticket_mismatch')
            finally:
                os.close(marker_fd)
            journal_fd = os.open(directory / 'transaction.json', os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(journal_fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                        info.st_mode & 0o077 or info.st_size > 65536):
                    raise Refused('unsafe_transaction_journal')
                raw = os.read(journal_fd, 65537)
            finally:
                os.close(journal_fd)

            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise Refused('duplicate_journal_field')
                    result[key] = value
                return result

            try:
                record = json.loads(raw, object_pairs_hook=unique)
            except (ValueError, UnicodeError) as exc:
                raise Refused('invalid_transaction_journal') from exc
            if (type(expected_transaction_id) is not str or
                    len(expected_transaction_id) != 32 or
                    any(c not in '0123456789abcdef' for c in expected_transaction_id) or
                    type(record) is not dict or
                    record.get('id') != expected_transaction_id or
                    record.get('phase') not in ('committed', 'rolled_back', 'aborted')):
                raise Refused('transaction_not_terminal')
            intent_path = directory / 'maintenance-intent.json'
            if require_intent:
                intent_fd = os.open(intent_path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    intent_info = os.fstat(intent_fd)
                    if (not stat.S_ISREG(intent_info.st_mode) or
                            intent_info.st_uid != os.getuid() or
                            intent_info.st_mode & 0o077 or intent_info.st_size > 4096):
                        raise Refused('unsafe_maintenance_intent')
                    intent_raw = os.read(intent_fd, 4097)
                finally:
                    os.close(intent_fd)
                try:
                    intent = json.loads(intent_raw, object_pairs_hook=unique)
                except (ValueError, UnicodeError) as exc:
                    raise Refused('invalid_maintenance_intent') from exc
                if (type(intent) is not dict or
                        intent.get('id') != expected_transaction_id or
                        intent.get('source') != record.get('source') or
                        intent.get('ticket_sha256') != hashlib.sha256(ticket).hexdigest()):
                    raise Refused('maintenance_intent_mismatch')
            os.unlink(marker_path)
            if require_intent:
                os.unlink(intent_path)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            os.close(job_fd)
    finally:
        os.close(admission_fd)
