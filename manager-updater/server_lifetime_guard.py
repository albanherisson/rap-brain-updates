"""Patch a pinned server.py into an isolated output copy, never in place.

The inserted lifetime guard keeps a shared OS lock for the complete life of
both the HTTP parent and its worker subprocess. An external updater acquires
the same file exclusively, nonblocking, only after stopping verified processes.
During its restart handoff a durable marker admits only a child launched with
the matching maintenance ticket. The marker must be created under the exclusive
lock and retained until the transaction reaches a terminal state.
This is a source preparation step, not a distribution or production installer.
"""
import ast
import hashlib
from pathlib import Path

EXPECTED_SOURCE_SHA256 = '4380ab4fd97d727ced4521eb66b11004e21f9f15c0eafaee955f1f0145913ad7'

GUARD = '''# Rap Brain update lifetime guard v2 — preserve through upgrades.
def __rb_update_guard_v2():
    import fcntl as __rb_fcntl
    import os as __rb_os
    import stat as __rb_stat
    import secrets as __rb_secrets
    from pathlib import Path as __rb_Path
    __rb_root = __rb_Path.home() / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
    if any(__rb_part.is_symlink() for __rb_part in
           (__rb_root, *__rb_root.parents)):
        raise RuntimeError('update_guard_unsafe_directory')
    __rb_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    __rb_info = __rb_root.stat()
    if (__rb_info.st_uid != __rb_os.getuid() or
            not __rb_stat.S_ISDIR(__rb_info.st_mode) or
            __rb_info.st_mode & 0o077):
        raise RuntimeError('update_guard_private_directory_required')
    __rb_lock = __rb_os.open(__rb_root / 'update.lock',
        __rb_os.O_CREAT | __rb_os.O_RDWR | __rb_os.O_NOFOLLOW, 0o600)
    try:
        __rb_fcntl.flock(__rb_lock, __rb_fcntl.LOCK_SH | __rb_fcntl.LOCK_NB)
    except BaseException:
        __rb_os.close(__rb_lock)
        raise RuntimeError('update_in_progress')
    try:
        try:
            __rb_ticket_fd = __rb_os.open(__rb_root / 'maintenance.ticket',
                __rb_os.O_RDONLY | __rb_os.O_NOFOLLOW)
        except FileNotFoundError:
            __rb_ticket_fd = None
        if __rb_ticket_fd is not None:
            try:
                __rb_ticket_info = __rb_os.fstat(__rb_ticket_fd)
                if (__rb_ticket_info.st_uid != __rb_os.getuid() or
                        not __rb_stat.S_ISREG(__rb_ticket_info.st_mode) or
                        __rb_ticket_info.st_mode & 0o077):
                    raise RuntimeError('invalid_maintenance_ticket')
                __rb_expected = __rb_os.read(__rb_ticket_fd, 129)
                __rb_provided = __rb_os.environ.get('RB_UPDATE_LAUNCH_TICKET', '')
                if (len(__rb_expected) != 65 or __rb_expected[-1:] != b'\\n' or
                        any(__rb_c not in b'0123456789abcdef' for __rb_c in __rb_expected[:-1]) or
                        not __rb_secrets.compare_digest(__rb_provided.encode('ascii', 'ignore'),
                                                        __rb_expected[:-1])):
                    raise RuntimeError('maintenance_launch_refused')
            finally:
                __rb_os.close(__rb_ticket_fd)
    except BaseException:
        __rb_os.close(__rb_lock)
        raise
    # Retain the descriptor until process exit. Worker subprocesses use the
    # same entrypoint and acquire their own shared lifetime lock.
    return __rb_lock

'''


def prepare(raw, expected_sha256=EXPECTED_SOURCE_SHA256):
    """Lifetime lock only, retained for isolated process-lock fixtures."""
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('unknown_server_baseline')
    source = raw.decode('utf-8')
    if 'Rap Brain update lifetime guard' in source or '__rb_update_guard_v' in source:
        raise ValueError('already_patched')
    tree = ast.parse(source)
    candidates = [n for n in tree.body if isinstance(n, ast.If)
                  and isinstance(n.test, ast.Compare)
                  and isinstance(n.test.left, ast.Name)
                  and n.test.left.id == '__name__'
                  and len(n.test.ops) == 1 and isinstance(n.test.ops[0], ast.Eq)
                  and len(n.test.comparators) == 1
                  and isinstance(n.test.comparators[0], ast.Constant)
                  and n.test.comparators[0].value == '__main__']
    if len(candidates) != 1 or candidates[0] is not tree.body[-1]:
        raise ValueError('unsupported_entrypoint')
    main = candidates[0]
    if not main.body or main.body[0].lineno <= main.lineno:
        raise ValueError('unexpected_entrypoint_body')
    lines = source.splitlines(keepends=True)
    if not lines[main.lineno - 1].startswith('if __name__ == '):
        raise ValueError('unexpected_entrypoint_format')
    # The only generated change is the guard declaration and the first
    # statement in __main__. No SQL, routes, lyrics or other code is rewritten.
    lines.insert(main.body[0].lineno - 1, '    __rb_guard_fd = __rb_update_guard_v2()\n')
    lines.insert(main.lineno - 1, GUARD)
    candidate = ''.join(lines).encode('utf-8')
    compile(candidate, 'server.py', 'exec')
    return candidate


POST_GATE = '''# Rap Brain maintenance POST admission gate v1.
def _rb_update_blocks_posts_v1():
    import os as __rb_os
    from pathlib import Path as __rb_Path
    __rb_state = (__rb_Path.home() / 'Downloads' /
                  'RapBrainManagerBackups' / 'secure-update')
    return __rb_os.path.lexists(__rb_state / 'maintenance.ticket')

'''


def prepare_admission(raw, expected_sha256=EXPECTED_SOURCE_SHA256):
    """Prepare a pinned isolated server with lifetime and POST admission gates."""
    candidate = prepare(raw, expected_sha256)
    source = candidate.decode('utf-8')
    tree = ast.parse(source)
    handlers = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler']
    if len(handlers) != 1:
        raise ValueError('unsupported_http_handler')
    handler = handlers[0]
    posts = [n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == 'do_POST']
    if len(posts) != 1 or not posts[0].body or not isinstance(posts[0].body[0], ast.Try):
        raise ValueError('unsupported_post_flow')
    post = posts[0]
    lines = source.splitlines(keepends=True)
    if (lines[handler.lineno - 1].strip() != 'class Handler(BaseHTTPRequestHandler):' or
            lines[post.lineno - 1].strip() != 'def do_POST(self):' or
            post.body[0].lineno <= post.lineno):
        raise ValueError('unsupported_post_format')
    # Before request-body parsing or route dispatch. The GET health endpoint
    # remains available, but every POST (including jobs/audio) is rejected.
    lines.insert(post.body[0].lineno - 1,
                 "        if _rb_update_blocks_posts_v1():\n"
                 "            return self.send({'error': 'update_in_progress'}, 503)\n")
    lines.insert(handler.lineno - 1, POST_GATE)
    output = ''.join(lines).encode('utf-8')
    compile(output, 'server.py', 'exec')
    return output


def prepare_copy(source, destination):
    source = Path(source).absolute()
    destination = Path(destination).absolute()
    if source.is_symlink() or not source.is_file() or destination.exists():
        raise ValueError('unsafe_source_or_destination')
    if destination.is_relative_to(source.parent) or destination.parent.is_symlink():
        raise ValueError('output_must_be_separate')
    candidate = prepare_admission(source.read_bytes())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(candidate)
    return hashlib.sha256(candidate).hexdigest()
