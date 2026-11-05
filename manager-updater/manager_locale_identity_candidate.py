"""Prepare a copy-only fix for macOS process dates under French locale.

The already signed helper stays byte-for-byte intact. A later signed helper
release may include this exact replacement after its own copy gate.
"""
import hashlib


BASELINE = 'c80542d3cc4c37125bc539e2f3848040ccdf245385c2f73d475e68641b5dcb74'
OLD = 'stdin=subprocess.DEVNULL, check=True)'
NEW = ("stdin=subprocess.DEVNULL, check=True,\n"
       "                                env={'LC_ALL':'C','LANG':'C',"
       "'PATH':'/usr/bin:/bin'})")


def prepare(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != BASELINE:
        raise ValueError('process_identity_baseline_changed')
    source = raw.decode('utf-8')
    if source.count(OLD) != 1:
        raise ValueError('process_identity_anchor_changed')
    output = source.replace(OLD, NEW, 1).encode('utf-8')
    compile(output, 'process_start_identity.py', 'exec')
    return output
