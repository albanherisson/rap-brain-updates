"""Cross-process advisory lock for disposable supervisor tests ONLY.

This module does not signal processes, install software, or touch user data.
"""
import contextlib
import fcntl
import os
import stat

from disposable_supervisor_lab import check


class LockBusy(RuntimeError):
    pass


@contextlib.contextmanager
def exclusive_fixture_lock(root):
    root = check(root)
    lock = root / ".update.lock"
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(lock, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Unsafe update lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockBusy("Another fixture update is running") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def locked_fixture_transaction(root, *, health=True, crash=None):
    from disposable_supervisor_lab import run
    with exclusive_fixture_lock(root):
        return run(root, health=health, crash=crash)
