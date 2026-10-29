import os
from pathlib import Path
import tempfile
import unittest

from creative_release import Refused, digest
from isolated_runtime_runner import run_disposable


FIXTURE = b'''import os
from http.server import BaseHTTPRequestHandler, HTTPServer
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
    HTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
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
                report = run_disposable(source, home, digest(FIXTURE), timeout=8,
                                        listener_check=lambda port, pid: True)
            except Refused as exc:
                marker = home / 'fixture-started'
                requested = home / 'fixture-request'
                self.fail(f'{exc}; child_started={marker.exists()}; '
                          f'port={marker.read_text() if marker.exists() else "missing"}; '
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
