"""Read-only start identity for a retained Manager Popen child.

This supplements, but never replaces, the owned Popen handle. The caller must
check the handle again immediately before a future signal; no signal here.
"""
import re
import subprocess

from creative_release import Refused

START = re.compile(r'^[A-Z][a-z]{2} +[A-Z][a-z]{2} +[ 0-9]{1,2} +'
                   r'[0-9]{2}:[0-9]{2}:[0-9]{2} +[0-9]{4}$')


def parse_start(raw, pid):
    if (type(pid) is not int or pid < 2 or type(raw) is not str or
            len(raw) > 96 or len(raw.splitlines()) != 1 or
            not START.fullmatch(raw.strip())):
        raise Refused('process_start_unverified')
    return str(pid) + ':' + ' '.join(raw.split())


def read_start(pid):
    if type(pid) is not int or pid < 2:
        raise Refused('process_pid_invalid')
    try:
        result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart='],
                                capture_output=True, text=True, timeout=5,
                                stdin=subprocess.DEVNULL, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('process_start_unavailable') from exc
    if result.stderr:
        raise Refused('process_start_unexpected_output')
    return parse_start(result.stdout, pid)


def require_live_owned_handle(handle, recorded_start):
    if (handle is None or type(getattr(handle, 'pid', None)) is not int or
            handle.pid < 2 or not callable(getattr(handle, 'poll', None)) or
            handle.poll() is not None):
        raise Refused('owned_handle_not_alive')
    current = read_start(handle.pid)
    if current != recorded_start or handle.poll() is not None:
        raise Refused('owned_process_start_changed')
    return current
