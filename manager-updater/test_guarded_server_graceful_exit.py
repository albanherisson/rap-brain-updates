"""Full subprocess drill on disposable guarded HTTP parent and worker."""
import hashlib
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from authenticated_runtime_client import read_runtime_proof
from owned_graceful_stop import graceful_stop_owned
from server_graceful_shutdown_candidate import prepare
from worker_activity_gate import begin_maintenance


SOURCE = b'''import json, os, subprocess, sys, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from socketserver import TCPServer
WORKER_PROCESS = None
AUDIO_LOCK = threading.Lock()
AUDIO_STATE = {'process': None}
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send(self, data, code=200):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        return self.send({'ok': True})
    def do_POST(self):
        try:
            return self.send({'accepted': True})
        except Exception:
            return self.send({'error': True}, 500)
def job_runner(*args):
    raise AssertionError('no job in fixture')
def resume_jobs():
    return None
def worker_main():
    resume_jobs()
    while True: time.sleep(.05)
def supervise_worker():
    global WORKER_PROCESS
    WORKER_PROCESS = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if __name__ == '__main__':
    if '--worker' in sys.argv:
        worker_main()
        sys.exit(0)
    threading.Thread(target=supervise_worker, daemon=True).start()
    server = TCPServer(('127.0.0.1', 0), Handler)
    print('PORT:' + str(server.server_address[1]), flush=True)
    try:
        server.serve_forever()
    finally:
        if WORKER_PROCESS is not None and WORKER_PROCESS.poll() is None:
            WORKER_PROCESS.terminate()
            WORKER_PROCESS.wait(timeout=3)
        server.server_close()
'''


class GuardedExitTests(unittest.TestCase):
    def test_owned_parent_worker_and_data_survive_graceful_stop(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            home = root / 'home'
            state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
            state.mkdir(parents=True, mode=0o700)
            source = root / 'source'
            data = source / 'data'
            data.mkdir(parents=True)
            (data / 'ollama_model.json').write_bytes(b'{"model":"fixture"}')
            db = data / 'rapbrain.sqlite3'
            with sqlite3.connect(db) as con:
                con.execute('CREATE TABLE jobs (status TEXT)')
                con.execute("INSERT INTO jobs VALUES ('done')")
            script = source / 'server.py'
            candidate = prepare(SOURCE, hashlib.sha256(SOURCE).hexdigest())
            script.write_bytes(candidate)
            expected = hashlib.sha256(candidate).hexdigest()
            before = {p.name: p.read_bytes() for p in data.iterdir()}
            env = dict(os.environ, HOME=str(home), RB_UPDATE_PROBE_TOKEN='c' * 64)
            child = subprocess.Popen([sys.executable, '-u', str(script)], cwd=source,
                                     env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     start_new_session=True, close_fds=True)
            try:
                ready, _, _ = select.select([child.stdout], [], [], 15)
                if not ready:
                    detail = (child.stderr.read(1000).decode(errors='replace')
                              if child.poll() is not None else 'child_alive_no_ready')
                    self.fail('guarded_fixture_not_ready: ' + detail)
                line = child.stdout.readline().decode()
                if not line.startswith('PORT:'):
                    detail = (child.stderr.read(1000).decode(errors='replace')
                              if child.poll() is not None else 'child_alive_no_port')
                    self.fail('guarded_fixture_no_port: ' + line + ' / ' + detail)
                port = int(line.removeprefix('PORT:'))
                # This container cannot run ps -p ("lookup self"); the
                # start-token parser is covered by its separate unit tests.
                start = f'{child.pid}:fixture-start'
                with (patch('authenticated_runtime_client.assert_owned_listener', return_value=True),
                      patch('owned_graceful_stop.assert_owned_listener', return_value=True),
                      patch('runtime_evidence.require_live_owned_handle', return_value=start),
                      patch('runtime_evidence.read_start', return_value='worker:fixture-start'),
                      patch('runtime_evidence.read_owned_group') as census,
                      patch('owned_graceful_stop._assert_group_gone', return_value=None)):
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            report = read_runtime_proof(port, 'c' * 64,
                                                        expected_parent_pid=child.pid)
                            break
                        except Exception:
                            if time.monotonic() >= deadline:
                                raise
                            time.sleep(.05)
                    self.assertGreater(report['worker_pid'], 1)
                    # Bind the mocked OS census to the actual worker PID.
                    census.return_value = frozenset((child.pid, report['worker_pid']))
                    ticket = b'b' * 64 + b'\n'
                    begin_maintenance(state, ticket)
                    with graceful_stop_owned(
                            source=source, state=state, handle=child,
                            recorded_start=start, recorded_server_sha256=expected,
                            token='c' * 64, ticket=ticket, port=port) as lease:
                        self.assertEqual(child.poll(), 0)
                        self.assertIsNotNone(lease.fd)
                        self.assertTrue((state / 'maintenance.ticket').exists())
                self.assertEqual(before, {p.name: p.read_bytes() for p in data.iterdir()})
            finally:
                if child.poll() is None:
                    # Only the live, separate session created by this fixture.
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=3)
                child.stdout.close()
                child.stderr.close()


if __name__ == '__main__':
    unittest.main()
