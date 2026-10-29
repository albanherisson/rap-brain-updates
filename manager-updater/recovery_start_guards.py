"""Extend the isolated final candidates with crash recovery startup checks.

The historical Mac probes and their pinned preparers remain byte-for-byte
unchanged. These wrappers only compile new candidates in memory; they do not
touch an installed server, Manager, or database.
"""
import ast

from beta14_owned_identity_candidate import prepare as prepare_owned_launcher
from server_graceful_shutdown_candidate import prepare as prepare_graceful_server


SERVER_CHECK = '''# Refuse direct startup if a crashed update lacks its ticket.
def __rb_check_terminal_without_ticket_v1():
    import json as __rb_json
    import os as __rb_os
    import stat as __rb_stat
    from pathlib import Path as __rb_Path
    __rb_root = (__rb_Path.home() / 'Downloads' /
                 'RapBrainManagerBackups' / 'secure-update')
    # The lifetime guard already validated this private directory and holds
    # its shared lock. A matching ticket is required for an updater restart.
    if __rb_os.path.lexists(__rb_root / 'maintenance.ticket'):
        return
    if __rb_os.path.lexists(__rb_root / 'maintenance-intent.json'):
        raise RuntimeError('update_recovery_required')
    __rb_path = __rb_root / 'transaction.json'
    if not __rb_os.path.lexists(__rb_path):
        return
    __rb_fd = __rb_os.open(__rb_path, __rb_os.O_RDONLY | __rb_os.O_NOFOLLOW)
    try:
        __rb_info = __rb_os.fstat(__rb_fd)
        if (__rb_info.st_uid != __rb_os.getuid() or
                not __rb_stat.S_ISREG(__rb_info.st_mode) or
                __rb_info.st_mode & 0o077 or __rb_info.st_size > 8192):
            raise RuntimeError('update_recovery_required')
        __rb_raw = __rb_os.read(__rb_fd, 8193)
    finally:
        __rb_os.close(__rb_fd)
    def __rb_unique(pairs):
        __rb_data = {}
        for __rb_key, __rb_value in pairs:
            if __rb_key in __rb_data:
                raise ValueError('duplicate_journal_field')
            __rb_data[__rb_key] = __rb_value
        return __rb_data
    try:
        __rb_record = __rb_json.loads(__rb_raw, object_pairs_hook=__rb_unique)
    except (ValueError, UnicodeError):
        raise RuntimeError('update_recovery_required')
    __rb_id = __rb_record.get('id') if type(__rb_record) is dict else None
    if (type(__rb_record) is not dict or
            __rb_record.get('phase') not in ('committed', 'rolled_back', 'aborted') or
            __rb_record.get('source') != str(__rb_Path(__file__).resolve().parent) or
            type(__rb_record.get('sequence')) is not int or
            __rb_record['sequence'] < 1 or
            type(__rb_record.get('mode')) is not int or
            not 0 <= __rb_record['mode'] <= 0o777 or
            type(__rb_id) is not str or len(__rb_id) != 32 or
            any(__rb_c not in '0123456789abcdef' for __rb_c in __rb_id)):
        raise RuntimeError('update_recovery_required')

'''


def prepare_server(raw, expected_sha256=None):
    candidate = (prepare_graceful_server(raw) if expected_sha256 is None else
                 prepare_graceful_server(raw, expected_sha256)).decode('utf-8')
    tree = ast.parse(candidate)
    main = tree.body[-1]
    if (not isinstance(main, ast.If) or not main.body or
            not isinstance(main.body[0], ast.Assign) or
            len(main.body[0].targets) != 1 or
            not isinstance(main.body[0].targets[0], ast.Name) or
            main.body[0].targets[0].id != '__rb_guard_fd'):
        raise ValueError('unsupported_guarded_server_entrypoint')
    lines = candidate.splitlines(keepends=True)
    # The base lifetime guard must acquire the shared lock first. The check
    # runs before worker_main(), init(), or any database access.
    line = main.body[0].end_lineno
    lines.insert(line, '    __rb_check_terminal_without_ticket_v1()\n')
    lines.insert(main.lineno - 1, SERVER_CHECK)
    output = ''.join(lines).encode('utf-8')
    compile(output, 'server.py', 'exec')
    return output


def prepare_launcher(raw, expected_sha256=None):
    candidate = (prepare_owned_launcher(raw) if expected_sha256 is None else
                 prepare_owned_launcher(raw, expected_sha256)).decode('utf-8')
    anchor = "    if __rb_os.path.lexists(__rb_state / 'maintenance.ticket'):\n        raise RuntimeError('update_recovery_required')\n"
    if candidate.count(anchor) != 1:
        raise ValueError('unsupported_beta14_launch_gate')
    candidate = candidate.replace(anchor, anchor +
        "    if __rb_os.path.lexists(__rb_state / 'maintenance-intent.json'):\n"
        "        raise RuntimeError('update_recovery_required')\n", 1)
    output = candidate.encode('utf-8')
    compile(output, 'launch_manager.py', 'exec')
    return output
