"""Run an already staged, disposable server on a private home and port.

This is a lab primitive, not a production install or owner-Mac entrypoint.
Only the process group created here may be stopped. No active server or app
handle is accepted or signalled.
"""
import json
import http.client
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

from authenticated_runtime_client import assert_owned_listener
from creative_release import Refused, digest
from isolated_runtime_port import disposable_environment


def free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    if port == 8765 or port < 1024:
        raise Refused('isolated_port_unavailable')
    return port


def run_disposable(source, home, expected_sha256, *, port=None, timeout=15,
                   listener_check=assert_owned_listener):
    source = Path(source).absolute()
    home = Path(home).absolute()
    script = source / 'server.py'
    if (any(path.is_symlink() for path in (source, *source.parents, script)) or
            not script.is_file() or
            source != home / 'Downloads' / 'rap-brain' or
            os.path.lexists(source / 'data') or not 1 <= timeout <= 30):
        raise Refused('isolated_layout_invalid')
    raw = script.read_bytes()
    port = free_local_port() if port is None else port
    selected = disposable_environment(raw, expected_sha256, port, home)
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C', **selected}
    # No secrets, update ticket, original HOME, PYTHONPATH or inherited runtime
    # configuration can enter the isolated subprocess.
    child = subprocess.Popen([sys.executable, '-B', '-u', str(script)],
                             cwd=source, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise Refused('isolated_server_exited')
            try:
                listener_check(port, child.pid)
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=0.5)
                try:
                    connection.request('GET', '/api/status')
                    response = connection.getresponse()
                    if response.status != 200:
                        raise Refused('isolated_status_invalid')
                    raw_status = response.read(65_537)
                finally:
                    connection.close()
                listener_check(port, child.pid)
                if len(raw_status) > 65_536 or type(json.loads(raw_status)) is not dict:
                    raise Refused('isolated_status_invalid')
                return {'status_ok': True, 'port': port, 'pid': child.pid}
            except (OSError, http.client.HTTPException, Refused) as exc:
                if isinstance(exc, Refused) and str(exc) not in ('listener_identity_unavailable',):
                    raise
                time.sleep(0.1)
        raise Refused('isolated_status_timeout')
    finally:
        # start_new_session gives this child a distinct process group. The
        # retained Popen handle must still identify its leader before killpg.
        if child.poll() is None and os.getpgid(child.pid) == child.pid:
            os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if child.poll() is None and os.getpgid(child.pid) == child.pid:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=3)
