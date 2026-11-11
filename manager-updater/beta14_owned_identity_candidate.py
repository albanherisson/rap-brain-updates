"""Prepare an isolated Beta 14 launcher that records its owned child's identity.

No process is started by this preparer. Missing OS start evidence disables a
future updater while preserving Beta 14's ordinary launch behavior.
"""
import ast

from beta14_runtime_token_candidate import prepare as prepare_token, EXPECTED_LAUNCHER_SHA256


def prepare(raw, expected_sha256=EXPECTED_LAUNCHER_SHA256):
    source = prepare_token(raw, expected_sha256).decode('utf-8')
    tree = ast.parse(source)
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name == 'handle_launch_request']
    if len(funcs) != 1:
        raise ValueError('unsupported_launch_handler')
    lines = source.splitlines(keepends=True)
    calls = [n for n in ast.walk(funcs[0]) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == 'Popen'
             and isinstance(n.func.value, ast.Name) and n.func.value.id == 'subprocess']
    if len(calls) != 1:
        raise ValueError('unsupported_owned_spawn')
    line = lines[calls[0].lineno - 1]
    if ("[sys.executable,'-u',str(script)]" not in line or
            'env=__rb_server_env)' not in line):
        raise ValueError('unexpected_server_command')
    lines.insert(calls[0].lineno - 1,
                 '            import hashlib as __rb_hashlib\n'
                 '            __rb_server_sha = __rb_hashlib.sha256(script.read_bytes()).hexdigest()\n')
    source = ''.join(lines)
    anchor = "        state['runtime_token']=__rb_token\n"
    if source.count(anchor) != 1:
        raise ValueError('unsupported_owned_state')
    source = source.replace(anchor, anchor +
        "        state['server_sha256']=__rb_server_sha\n"
        "        state['process_start_token']=None\n"
        "        try:\n"
        "            import re as __rb_re\n"
        "            __rb_ps=subprocess.run(['/bin/ps','-p',str(proc.pid),'-o','lstart='],\n"
        "                capture_output=True,text=True,timeout=5,stdin=subprocess.DEVNULL)\n"
        "            __rb_raw=__rb_ps.stdout.strip()\n"
        "            if (__rb_ps.returncode==0 and not __rb_ps.stderr and\n"
        "                    __rb_re.fullmatch(r'[A-Z][a-z]{2} +[A-Z][a-z]{2} +[ 0-9]{1,2} +[0-9]{2}:[0-9]{2}:[0-9]{2} +[0-9]{4}',__rb_raw) and\n"
        "                    proc.poll() is None):\n"
        "                state['process_start_token']=str(proc.pid)+':'+ ' '.join(__rb_raw.split())\n"
        "        except (OSError,subprocess.SubprocessError):\n"
        "            pass\n", 1)
    output = source.encode('utf-8')
    compile(output, 'launch_manager.py', 'exec')
    return output
