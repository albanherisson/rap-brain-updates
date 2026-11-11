import os
import subprocess
from pathlib import Path
import tempfile
import sys
import unittest

from creative_release import Refused, digest
from isolated_runtime_runner import run_disposable
from authenticated_runtime_client import assert_owned_listener


FIXTURE = b'''import os
from http.server import BaseHTTPRequestHandler
from socketserver import TCPServer
PORT = int(os.getenv('RAP_BRAIN_PORT', '8765'))
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from pathlib import Path
        Path(os.environ['HOME'], 'fixture-request').write_text(self.path)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"ok":true}')
    def log_message(self, *args):
        pass
if __name__ == '__main__':
    from pathlib import Path
    Path(os.environ['HOME'], 'fixture-started').write_text(str(PORT))
    Path(os.environ['HOME'], 'fixture-prebind').write_text('ready')
    try:
        server = TCPServer(('127.0.0.1', PORT), Handler)
    except OSError as exc:
        Path(os.environ['HOME'], 'fixture-bind-error').write_text(repr(exc))
        raise
    Path(os.environ['HOME'], 'fixture-bound').write_text(str(server.server_address))
    server.serve_forever()
'''


class RunnerTests(unittest.TestCase):
    def test_private_home_and_owned_child_shutdown(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            home = root / 'home'
            source = home / 'Downloads' / 'rap-brain'
            source.mkdir(parents=True)
            (source / 'server.py').write_bytes(FIXTURE)
            try:
                def checked_listener(port, pid):
                    try:
                        return assert_owned_listener(port, pid)
                    except Refused:
                        inspect = subprocess.run(['/usr/sbin/lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-Fp'], capture_output=True, text=True)
                        (home / 'fixture-listener').write_text(f'expected={pid}; rc={inspect.returncode}; stdout={inspect.stdout[:400]!r}; stderr={inspect.stderr[:400]!r}')
                        raise
                options = ({'listener_check': checked_listener} if sys.platform == 'darwin' else
                           {'listener_check': lambda port, pid: True})
                report = run_disposable(source, home, digest(FIXTURE), timeout=8,
                                        **options)
            except Refused as exc:
                marker = home / 'fixture-started'
                requested = home / 'fixture-request'
                bound = home / 'fixture-bound'
                bind_error = home / 'fixture-bind-error'
                prebind = home / 'fixture-prebind'
                port_text = marker.read_text() if marker.exists() else ''
                inspect = subprocess.run(['/usr/sbin/lsof', '-nP', f'-iTCP:{port_text}', '-sTCP:LISTEN', '-Fp'], capture_output=True, text=True) if port_text.isdecimal() else None
                observed = home / 'fixture-listener'
                detail = observed.read_text() if observed.exists() else (f'rc={inspect.returncode}; stdout={inspect.stdout[:400]!r}; stderr={inspect.stderr[:400]!r}' if inspect else 'no port')
                self.fail(f'{exc}; listener={detail}; prebind={prebind.exists()}; bind_error={bind_error.read_text() if bind_error.exists() else "missing"}; child_started={marker.exists()}; '
                          f'port={marker.read_text() if marker.exists() else "missing"}; '
                          f'bound={bound.read_text() if bound.exists() else "missing"}; '
                          f'request={requested.read_text() if requested.exists() else "missing"}')
            self.assertTrue(report['status_ok'])
            self.assertNotEqual(report['port'], 8765)
            with self.assertRaises(ProcessLookupError):
                os.kill(report['pid'], 0)
            self.assertFalse((source / 'data').exists())

    def test_refuses_live_data_and_unknown_source(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            home = Path(folder) / 'home'
            source = home / 'Downloads' / 'rap-brain'
            source.mkdir(parents=True)
            (source / 'server.py').write_bytes(FIXTURE)
            (source / 'data').mkdir()
            with self.assertRaises(Refused):
                run_disposable(source, home, digest(FIXTURE), listener_check=lambda *x: True)
            (source / 'data').rmdir()
            (source / 'data').symlink_to(Path(folder))
            with self.assertRaises(Refused):
                run_disposable(source, home, digest(FIXTURE), listener_check=lambda *x: True)
