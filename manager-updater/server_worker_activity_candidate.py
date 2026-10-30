"""Experimental worker-gated server candidate, prepared only on isolated copies.

The pinned Mac-probed server_lifetime_guard.py remains byte-identical.
"""
import ast
from server_lifetime_guard import prepare_admission, EXPECTED_SOURCE_SHA256

WORKER_GATE = '''# Rap Brain worker activity gate v1.
_rb_original_job_runner_v1 = job_runner
_rb_original_worker_main_v1 = worker_main
def _rb_worker_state_v1():
    from pathlib import Path as __rb_Path
    return (__rb_Path.home() / 'Downloads' /
            'RapBrainManagerBackups' / 'secure-update')

def _rb_guarded_job_runner_v1(*args, **kwargs):
    import fcntl as __rb_fcntl
    import os as __rb_os
    import stat as __rb_stat
    __rb_state = _rb_worker_state_v1()
    __rb_fd = __rb_os.open(__rb_state / 'worker-job.lock',
        __rb_os.O_CREAT | __rb_os.O_RDWR | __rb_os.O_NOFOLLOW, 0o600)
    try:
        __rb_info = __rb_os.fstat(__rb_fd)
        if (__rb_info.st_uid != __rb_os.getuid() or
                not __rb_stat.S_ISREG(__rb_info.st_mode) or
                __rb_info.st_mode & 0o077):
            raise RuntimeError('unsafe_worker_job_lock')
        __rb_fcntl.flock(__rb_fd, __rb_fcntl.LOCK_SH | __rb_fcntl.LOCK_NB)
        if __rb_os.path.lexists(__rb_state / 'maintenance.ticket'):
            raise RuntimeError('maintenance_in_progress')
        return _rb_original_job_runner_v1(*args, **kwargs)
    finally:
        __rb_os.close(__rb_fd)

def _rb_guarded_worker_main_v1(*args, **kwargs):
    import os as __rb_os
    import time as __rb_time
    # A ticketed candidate waits before init()/resume_jobs() until the
    # transaction has reached a terminal phase and removed the marker.
    while __rb_os.path.lexists(_rb_worker_state_v1() / 'maintenance.ticket'):
        __rb_time.sleep(0.1)
    return _rb_original_worker_main_v1(*args, **kwargs)

job_runner = _rb_guarded_job_runner_v1
worker_main = _rb_guarded_worker_main_v1

'''


def prepare_worker_activity(raw, expected_sha256=EXPECTED_SOURCE_SHA256):
    """Prepare the isolated pinned server with HTTP and worker exclusion."""
    candidate = prepare_admission(raw, expected_sha256)
    source = candidate.decode('utf-8')
    tree = ast.parse(source)
    functions = {name: [n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == name] for name in ('job_runner', 'worker_main')}
    if any(len(nodes) != 1 or nodes[0].decorator_list for nodes in functions.values()):
        raise ValueError('unsupported_worker_flow')
    main = tree.body[-1]
    if not isinstance(main, ast.If) or not all(nodes[0].end_lineno < main.lineno
                                              for nodes in functions.values()):
        raise ValueError('unsupported_worker_order')
    lines = source.splitlines(keepends=True)
    lines.insert(main.lineno - 1, WORKER_GATE)
    output = ''.join(lines).encode('utf-8')
    compile(output, 'server.py', 'exec')
    return output

