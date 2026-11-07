"""Build the narrow Manager process-date repair from signed release bytes.

The retained Popen handle, process PID, server hash and runtime token remain
mandatory.  Only the representation of macOS's start date is normalized.
"""
import hashlib


LAUNCHER_SHA256 = '0175fa828072b999760570c6a7609bc424d2ea229977202a9880df7aaa742db6'
IDENTITY_SHA256 = '7ee015733994da740f6f6bfd5599fb4acc667297043362e1868602b5f333b4dc'


def _replace(raw, expected, changes, filename):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(filename + '_baseline_changed')
    source = raw.decode('utf-8')
    for old, new in changes:
        if source.count(old) != 1:
            raise ValueError(filename + '_anchor_changed')
        source = source.replace(old, new, 1)
    result = source.encode('utf-8')
    compile(result, filename, 'exec')
    return result


def launcher(raw):
    return _replace(raw, LAUNCHER_SHA256, [
        ('capture_output=True,text=True,timeout=5,stdin=subprocess.DEVNULL)\n'
         '            __rb_raw=__rb_ps.stdout.strip()',
         'capture_output=True,text=True,timeout=5,stdin=subprocess.DEVNULL,\n'
         "                env={'LC_ALL':'C','LANG':'C','PATH':'/usr/bin:/bin'})\n"
         "            __rb_raw=__rb_ps.stdout.replace('\\u00a0',' ').strip()"),
    ], 'launch_manager.py')


def identity(raw):
    return _replace(raw, IDENTITY_SHA256, [
        ('not START.fullmatch(raw.strip())):',
         "not START.fullmatch(raw.replace('\\u00a0', ' ').strip())):"),
        ("return str(pid) + ':' + ' '.join(raw.split())",
         "return str(pid) + ':' + ' '.join(raw.replace('\\u00a0', ' ').split())"),
    ], 'process_start_identity.py')


