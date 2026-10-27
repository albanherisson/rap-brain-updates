"""Prepare a fail-closed ordinary-launch gate in an isolated Beta 14 copy.

This does not install, sign, or execute the Manager. The exact source hash is
required. The gate only blocks ordinary launches while maintenance/recovery is
pending; it cannot stop an existing process or replace the server's own guard.
"""
import ast
import hashlib
from pathlib import Path

EXPECTED_LAUNCHER_SHA256 = '362ad3e1e3878cc49b90f76e212211e328e514b97c5a49b52921c0b4669964ba'

GATE = '''# Rap Brain ordinary launch gate v1.
def __rb_ordinary_launch_guard_v1(backup_dir, rap_dir):
    import json as __rb_json
    import os as __rb_os
    import stat as __rb_stat
    __rb_state = backup_dir / 'secure-update'
    if __rb_state.is_symlink():
        raise RuntimeError('unsafe_update_state')
    if not __rb_state.exists():
        return
    __rb_info = __rb_state.stat()
    if (__rb_info.st_uid != __rb_os.getuid() or
            not __rb_stat.S_ISDIR(__rb_info.st_mode) or
            __rb_info.st_mode & 0o077):
        raise RuntimeError('unsafe_update_state')
    if __rb_os.path.lexists(__rb_state / 'maintenance.ticket'):
        raise RuntimeError('update_recovery_required')
    __rb_journal = __rb_state / 'transaction.json'
    if __rb_os.path.lexists(__rb_journal):
        if __rb_journal.is_symlink():
            raise RuntimeError('update_recovery_required')
        __rb_jinfo = __rb_journal.stat()
        if (__rb_jinfo.st_uid != __rb_os.getuid() or
                not __rb_stat.S_ISREG(__rb_jinfo.st_mode) or
                __rb_jinfo.st_mode & 0o077 or
                __rb_jinfo.st_size > 8192):
            raise RuntimeError('update_recovery_required')
        try:
            with __rb_journal.open('rb') as __rb_stream:
                __rb_record = __rb_json.loads(__rb_stream.read(8193))
            __rb_id = __rb_record.get('id') if type(__rb_record) is dict else None
            if (type(__rb_record) is not dict or
                    __rb_record.get('phase') not in ('committed', 'rolled_back', 'aborted') or
                    __rb_record.get('source') != str(rap_dir) or
                    type(__rb_record.get('sequence')) is not int or
                    __rb_record['sequence'] < 1 or
                    type(__rb_record.get('mode')) is not int or
                    not 0 <= __rb_record['mode'] <= 0o777 or
                    type(__rb_id) is not str or len(__rb_id) != 32 or
                    any(__rb_c not in '0123456789abcdef' for __rb_c in __rb_id)):
                raise RuntimeError('update_recovery_required')
        except (ValueError, UnicodeError):
            raise RuntimeError('update_recovery_required')

'''


def prepare(raw, expected_sha256=EXPECTED_LAUNCHER_SHA256):
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('unknown_beta14_launcher')
    source = raw.decode('utf-8')
    if '__rb_ordinary_launch_guard_v1' in source:
        raise ValueError('already_patched')
    tree = ast.parse(source)
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name == 'handle_launch_request']
    if len(funcs) != 1:
        raise ValueError('unsupported_launcher')
    function = funcs[0]
    tries = [n for n in function.body if isinstance(n, ast.Try)]
    if len(tries) != 1 or not tries[0].body:
        raise ValueError('unsupported_launch_flow')
    attempt = tries[0]
    lines = source.splitlines(keepends=True)
    if (lines[function.lineno - 1].strip() !=
            'def handle_launch_request(root, rap_dir, backup_dir, state):' or
            lines[attempt.lineno - 1].strip() != 'try:' or
            attempt.body[0].lineno <= attempt.lineno):
        raise ValueError('unsupported_launch_format')
    # A refusal enters the existing exception handler and creates the same
    # launch-state report as other Beta 14 refusals. Never spawn on refusal.
    lines.insert(attempt.body[0].lineno - 1, '        __rb_ordinary_launch_guard_v1(backup_dir, rap_dir)\n')
    lines.insert(function.lineno - 1, GATE)
    candidate = ''.join(lines).encode('utf-8')
    compile(candidate, 'launch_manager.py', 'exec')
    return candidate


def prepare_copy(source, destination):
    source = Path(source).absolute()
    destination = Path(destination).absolute()
    if source.is_symlink() or not source.is_file() or destination.exists():
        raise ValueError('unsafe_source_or_destination')
    if destination.is_relative_to(source.parent) or destination.parent.is_symlink():
        raise ValueError('output_must_be_separate')
    candidate = prepare(source.read_bytes())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(candidate)
    return hashlib.sha256(candidate).hexdigest()
