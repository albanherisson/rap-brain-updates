"""Add a narrowly authenticated graceful stop to an isolated guarded server.

Only a future Manager-owned lifecycle may call this after the maintenance
marker and process ownership have been proved. This preparer never runs it.
"""
import ast

from server_worker_resume_candidate import prepare_worker_activity, EXPECTED_SOURCE_SHA256


STOP_ROUTE = '''# Rap Brain guarded graceful stop candidate v1.
_rb_previous_post_stop_v1 = Handler.do_POST
def _rb_guarded_stop_v1(self):
    if self.path.split('?', 1)[0] != '/api/manager-update-stop':
        return _rb_previous_post_stop_v1(self)
    import fcntl as __rb_fcntl
    import os as __rb_os
    import re as __rb_re
    import secrets as __rb_secrets
    import stat as __rb_stat
    import sys as __rb_sys
    import threading as __rb_threading
    from pathlib import Path as __rb_Path
    __rb_token = __rb_os.environ.get('RB_UPDATE_PROBE_TOKEN', '')
    __rb_supplied = self.headers.get('X-RB-Update-Token', '')
    __rb_ticket = self.headers.get('X-RB-Update-Ticket', '')
    if (not __rb_re.fullmatch(r'[0-9a-f]{64}', __rb_token) or
            not __rb_secrets.compare_digest(__rb_token, __rb_supplied) or
            not __rb_re.fullmatch(r'[0-9a-f]{64}', __rb_ticket)):
        return self.send({'error': 'not_found'}, 404)
    __rb_state = _rb_worker_state_v1()
    try:
        __rb_fd = __rb_os.open(__rb_state / 'worker-job.lock',
            __rb_os.O_CREAT | __rb_os.O_RDWR | __rb_os.O_NOFOLLOW, 0o600)
        try:
            __rb_info = __rb_os.fstat(__rb_fd)
            if (__rb_info.st_uid != __rb_os.getuid() or
                    not __rb_stat.S_ISREG(__rb_info.st_mode) or
                    __rb_info.st_mode & 0o077):
                raise RuntimeError('unsafe_worker_lock')
            __rb_fcntl.flock(__rb_fd, __rb_fcntl.LOCK_EX | __rb_fcntl.LOCK_NB)
            __rb_path = __rb_state / 'maintenance.ticket'
            __rb_marker = __rb_os.open(__rb_path, __rb_os.O_RDONLY | __rb_os.O_NOFOLLOW)
            try:
                __rb_info = __rb_os.fstat(__rb_marker)
                if (__rb_info.st_uid != __rb_os.getuid() or
                        not __rb_stat.S_ISREG(__rb_info.st_mode) or
                        __rb_info.st_mode & 0o077 or
                        not __rb_secrets.compare_digest(
                            __rb_os.read(__rb_marker, 66),
                            __rb_ticket.encode('ascii') + b'\\n')):
                    raise RuntimeError('maintenance_ticket_mismatch')
            finally:
                __rb_os.close(__rb_marker)
            with AUDIO_LOCK:
                __rb_audio = AUDIO_STATE.get('process')
                if __rb_audio is not None and __rb_audio.poll() is None:
                    raise RuntimeError('audio_capture_active')
            __rb_worker = WORKER_PROCESS
            if __rb_worker is None or __rb_worker.poll() is not None:
                raise RuntimeError('worker_identity_unknown')
            __rb_args = getattr(__rb_worker, 'args', None)
            if (type(__rb_args) not in (tuple, list) or len(__rb_args) != 3 or
                    __rb_args[0] != __rb_sys.executable or
                    __rb_args[1] != str(__rb_Path(__file__).resolve())):
                raise RuntimeError('worker_script_changed')
            __rb_result = self.send({'stopping': True}, 202)
            __rb_threading.Thread(target=self.server.shutdown, daemon=True).start()
            return __rb_result
        finally:
            __rb_os.close(__rb_fd)
    except (OSError, RuntimeError, BlockingIOError):
        return self.send({'error': 'update_stop_refused'}, 503)

Handler.do_POST = _rb_guarded_stop_v1

'''


def prepare(raw, expected_sha256=EXPECTED_SOURCE_SHA256):
    candidate = prepare_worker_activity(raw, expected_sha256)
    source = candidate.decode('utf-8')
    tree = ast.parse(source)
    main = tree.body[-1]
    if not isinstance(main, ast.If) or main.col_offset != 0:
        raise ValueError('unsupported_server_entrypoint')
    lines = source.splitlines(keepends=True)
    lines.insert(main.lineno - 1, STOP_ROUTE)
    output = ''.join(lines).encode('utf-8')
    compile(output, 'server.py', 'exec')
    return output
