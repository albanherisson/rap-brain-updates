from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

from creative_release import Refused
from owned_graceful_stop import graceful_stop_owned, _stop_response


class StopHandler(BaseHTTPRequestHandler):
    seen = None

    def log_message(self, *_):
        pass

    def do_POST(self):
        StopHandler.seen = (self.path, self.headers.get('X-RB-Update-Token'),
                            self.headers.get('X-RB-Update-Ticket'))
        raw = json.dumps({'stopping': True}).encode()
        self.send_response(202)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class OwnedHandle:
    pid = 5100

    def __init__(self, *, hangs=False):
        self.hangs = hangs
        self.exited = False

    def wait(self, timeout):
        if self.hangs:
            raise subprocess.TimeoutExpired(['server.py'], timeout)
        self.exited = True
        return 0

    def poll(self):
        return 0 if self.exited else None

    def terminate(self):
        raise AssertionError('must not signal the child')

    def kill(self):
        raise AssertionError('must not kill the child')


class GracefulStopTests(unittest.TestCase):
    def test_owned_stop_holds_lifetime_lock_after_both_processes_exit(self):
        server = HTTPServer(('127.0.0.1', 0), StopHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
                state = Path(temporary) / 'private'
                state.mkdir(mode=0o700)
                ticket = b'b' * 64 + b'\n'
                (state / 'maintenance.ticket').write_bytes(ticket)
                (state / 'update.lock').write_bytes(b'')
                (state / 'update.lock').chmod(0o600)
                kwargs = dict(source=Path(temporary), state=state,
                              handle=OwnedHandle(), recorded_start='start',
                              recorded_server_sha256='a' * 64,
                              token='c' * 64, ticket=ticket,
                              port=server.server_address[1])
                with (patch('owned_graceful_stop.collect_owned_idle_proof',
                            return_value=SimpleNamespace(parent_pid=5100, worker_pid=5101)),
                      patch('owned_graceful_stop.assert_owned_listener', return_value=True),
                      patch('owned_graceful_stop.subprocess.run',
                            return_value=Mock(stdout=f'{os.getpid()} 1 {os.getpid()}\n', stderr=''))):
                    with graceful_stop_owned(**kwargs) as lease:
                        self.assertEqual(StopHandler.seen,
                                         ('/api/manager-update-stop', 'c' * 64, 'b' * 64))
                        self.assertTrue(kwargs['handle'].exited)
                        self.assertIsNotNone(lease.fd)
                        self.assertEqual((state / 'maintenance.ticket').read_bytes(), ticket)
                        lease.release_to_ticketed_candidate()
                        self.assertIsNone(lease.fd)
                    kwargs['handle'] = OwnedHandle(hangs=True)
                    with self.assertRaisesRegex(Refused, 'did_not_exit'):
                        graceful_stop_owned(**kwargs)
                    self.assertEqual((state / 'maintenance.ticket').read_bytes(), ticket)
        finally:
            server.shutdown()
            thread.join(3)
            server.server_close()

    def test_stop_response_rejects_extra_or_duplicate_fields(self):
        for raw in (b'{"stopping":false}', b'{"stopping":true,"x":1}',
                    b'{"stopping":true,"stopping":true}'):
            with self.subTest(raw=raw), self.assertRaises(Refused):
                _stop_response(raw)


if __name__ == '__main__':
    unittest.main()
