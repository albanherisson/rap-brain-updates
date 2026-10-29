"""Prepare an isolated Beta 14 launcher with an owned server proof token.

The exact original launcher and its already-pinned ordinary-launch gate stay
untouched. No app is installed, signed, or executed by this preparer.
"""
import ast

from beta14_launch_gate import prepare as prepare_launch_gate, EXPECTED_LAUNCHER_SHA256


def prepare(raw, expected_sha256=EXPECTED_LAUNCHER_SHA256):
    candidate = prepare_launch_gate(raw, expected_sha256).decode('utf-8')
    tree = ast.parse(candidate)
    funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name == 'handle_launch_request']
    if len(funcs) != 1:
        raise ValueError('unknown_launch_handler')
    calls = [node for node in ast.walk(funcs[0]) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == 'Popen'
             and isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess']
    if len(calls) != 1 or calls[0].lineno != calls[0].end_lineno:
        raise ValueError('unsupported_server_spawn')
    lines = candidate.splitlines(keepends=True)
    line = lines[calls[0].lineno - 1]
    if (not line.startswith('            proc=subprocess.Popen(') or
            'start_new_session=True,close_fds=True)' not in line or
            line.count('subprocess.Popen(') != 1 or 'env=' in line):
        raise ValueError('unsupported_server_spawn_format')
    lines[calls[0].lineno - 1] = line.replace(
        'start_new_session=True,close_fds=True)',
        'start_new_session=True,close_fds=True,env=__rb_server_env)', 1)
    lines.insert(calls[0].lineno - 1,
                 '            import secrets as __rb_secrets\n'
                 '            __rb_token = __rb_secrets.token_hex(32)\n'
                 "            __rb_server_env = dict(os.environ, RB_UPDATE_PROBE_TOKEN=__rb_token)\n")
    output = ''.join(lines)
    # Immediately after the retained Popen handle is recorded, retain the
    # token in the same private supervisor state. Never include it in reports.
    anchor = "        state['process']=proc\n"
    if output.count(anchor) != 1:
        raise ValueError('unsupported_handle_storage')
    output = output.replace(anchor, anchor + "        state['runtime_token']=__rb_token\n", 1)
    prepared = output.encode('utf-8')
    compile(prepared, 'launch_manager.py', 'exec')
    return prepared
