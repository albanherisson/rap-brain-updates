"""Exact source replacements for a future signed, offline Manager repair."""
import hashlib

PROOF_BASELINE = '491a6f41b33f87ebceb9b00d40d2c39ffbdab7be132559cb82a4782640006cf6'
HELPER_BASELINE = 'bf6acc6b52a0ce7223bdb108d3de36e523c4c5734a6b3de44ddeaf2256fb7f15'


def _replace(raw, baseline, old, new, name):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != baseline:
        raise ValueError(name + '_baseline_changed')
    source = raw.decode('utf-8')
    if source.count(old) != 1:
        raise ValueError(name + '_anchor_changed')
    result = source.replace(old, new, 1).encode('utf-8')
    compile(result, name + '.py', 'exec')
    return result


def prepare_proof(raw):
    old = '                                stdin=subprocess.DEVNULL)'
    new = ("                                stdin=subprocess.DEVNULL,\n"
           "                                env={'LC_ALL':'C','LANG':'C',"
           "'PATH':'/usr/bin:/bin'})")
    return _replace(raw, PROOF_BASELINE, old, new, 'manager_handoff_proof')


def prepare_helper(raw):
    old = '    offline(source, launcher)\n    signed, archive = staged_release(state, identifier)'
    new = '''    # Give the native app time to honor the child's authenticated exit code.
    # No process is signalled here; an unrecognized listener still fails closed.
    import time
    deadline = time.monotonic() + 10
    while True:
        try:
            offline(source, launcher)
            break
        except Refused as exc:
            if str(exc) != 'rapbrain_or_manager_still_running' or time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    signed, archive = staged_release(state, identifier)'''
    return _replace(raw, HELPER_BASELINE, old, new, 'manager_update_helper')
