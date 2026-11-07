"""Experimental worker-gated server candidate, prepared only on isolated copies.

The pinned Mac-probed server_lifetime_guard.py remains byte-identical.
"""
import ast
from server_lifetime_guard import prepare_admission, EXPECTED_SOURCE_SHA256

WORKER_GATE = '''# Rap Brain worker activity gate v1.
_rb_original_job_runner_v1 = job_runner
_rb_original_worker_main_v1 = worker_main
_rb_original_resume_jobs_v1 = resume_jobs
def _rb_worker_state_v1():
    from pathlib import Path as __rb_Path
    return (__rb_Path.home() / 'Downloads' /
            'RapBrainManagerBackups' / 'secure-update')

def _rb_with_worker_lock_v1(original, *args, **kwargs):
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
        return original(*args, **kwargs)
    finally:
        __rb_os.close(__rb_fd)

def _rb_guarded_job_runner_v1(*args, **kwargs):
    return _rb_with_worker_lock_v1(_rb_original_job_runner_v1, *args, **kwargs)

def _rb_guarded_resume_jobs_v1(*args, **kwargs):
    return _rb_with_worker_lock_v1(_rb_original_resume_jobs_v1, *args, **kwargs)

def _rb_guarded_worker_main_v1(*args, **kwargs):
    import os as __rb_os
    import time as __rb_time
    # A ticketed candidate waits before init()/resume_jobs() until the
    # transaction has reached a terminal phase and removed the marker.
    while __rb_os.path.lexists(_rb_worker_state_v1() / 'maintenance.ticket'):
        __rb_time.sleep(0.1)
    return _rb_original_worker_main_v1(*args, **kwargs)

job_runner = _rb_guarded_job_runner_v1
resume_jobs = _rb_guarded_resume_jobs_v1
worker_main = _rb_guarded_worker_main_v1

'''

RUNTIME_PROOF = '''# Rap Brain authenticated read-only runtime proof v1.
_rb_previous_get_proof_v1 = Handler.do_GET
def _rb_runtime_proof_get_v1(self):
    if self.path.split('?', 1)[0] != '/api/manager-update-proof':
        return _rb_previous_get_proof_v1(self)
    import os as __rb_os
    import re as __rb_re
    import secrets as __rb_secrets
    import sys as __rb_sys
    __rb_token = __rb_os.environ.get('RB_UPDATE_PROBE_TOKEN', '')
    __rb_supplied = self.headers.get('X-RB-Update-Token', '')
    if (not __rb_re.fullmatch(r'[0-9a-f]{64}', __rb_token) or
            not __rb_secrets.compare_digest(__rb_token, __rb_supplied)):
        return self.send({'error': 'not_found'}, 404)
    __rb_worker = WORKER_PROCESS
    __rb_args = getattr(__rb_worker, 'args', None)
    __rb_script = str(__import__('pathlib').Path(__file__).resolve())
    __rb_worker_script_matches = (
        type(__rb_args) in (list, tuple) and len(__rb_args) == 3 and
        __rb_args[0] == __rb_sys.executable and __rb_args[1] == __rb_script)
    with AUDIO_LOCK:
        __rb_audio = AUDIO_STATE.get('process')
        __rb_audio_pid = (__rb_audio.pid if __rb_audio is not None and
                          __rb_audio.poll() is None else None)
    return self.send({
        'parent_pid': __rb_os.getpid(),
        'worker_pid': (__rb_worker.pid if __rb_worker is not None and
                       __rb_worker.poll() is None else None),
        'worker_script_matches': __rb_worker_script_matches,
        'audio_pid': __rb_audio_pid,
    }, 200)

Handler.do_GET = _rb_runtime_proof_get_v1

'''


def prepare_worker_activity(raw, expected_sha256=EXPECTED_SOURCE_SHA256):
    """Prepare the isolated pinned server with HTTP and worker exclusion."""
    candidate = prepare_admission(raw, expected_sha256)
    source = candidate.decode('utf-8')
    tree = ast.parse(source)
    functions = {name: [n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == name] for name in ('job_runner', 'worker_main', 'resume_jobs')}
    if any(len(nodes) != 1 or nodes[0].decorator_list for nodes in functions.values()):
        raise ValueError('unsupported_worker_flow')
    main = tree.body[-1]
    if not isinstance(main, ast.If) or not all(nodes[0].end_lineno < main.lineno
                                              for nodes in functions.values()):
        raise ValueError('unsupported_worker_order')
    lines = source.splitlines(keepends=True)
    lines.insert(main.lineno - 1, WORKER_GATE + RUNTIME_PROOF)
    output = ''.join(lines).encode('utf-8')
    compile(output, 'server.py', 'exec')
    return output

