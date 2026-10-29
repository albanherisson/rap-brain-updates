"""Disposable worker/maintenance gate primitive; not installed in Rap Brain.

The worker holds a shared lock for the entire job. Maintenance takes that lock
exclusively before creating a durable marker. A worker checks the marker while
holding its shared lock, so no job can slip between the idle check and marker.
The caller must retain the marker until commit or rollback is terminal.
"""
import fcntl
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


def _lock(directory, operation):
    fd = os.open(directory / 'worker-job.lock',
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
        fd = _lock(directory, fcntl.LOCK_SH)
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
    fd = _lock(directory, fcntl.LOCK_EX)
    try:
        path = directory / 'maintenance.ticket'
        marker = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(marker, 'wb') as stream:
                stream.write(ticket)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            # A partial marker deliberately remains: recovery must fail closed.
            raise
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.close(fd)
