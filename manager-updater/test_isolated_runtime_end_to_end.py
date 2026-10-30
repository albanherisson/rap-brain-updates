"""Exercise isolated staging, real HTTP health, process shutdown and cleanup together.

Uses only generated toy code. This is not a test of the owner's real server.
"""
import sys
import tempfile
from pathlib import Path
import unittest

from creative_release import digest
from isolated_runtime_lab import rehearse

ORIGINAL = b"PORT = 8765\n"
CANDIDATE = b"""import os
from http.server import BaseHTTPRequestHandler
from socketserver import TCPServer
PORT = int(os.getenv('RAP_BRAIN_PORT', '8765'))
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/api/status':
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
    def log_message(self, *args):
        pass
if __name__ == '__main__':
    with TCPServer(('127.0.0.1', PORT), Handler) as server:
        server.serve_forever()
"""

class EndToEndTests(unittest.TestCase):
    def test_live_http_in_throwaway_workspace(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            source = root / "owner-source-standin"
            workspace = root / "scratch"
            source.mkdir()
            workspace.mkdir()
            (source / "server.py").write_bytes(ORIGINAL)
            report = rehearse(source, CANDIDATE, digest(ORIGINAL), digest(CANDIDATE),
                              workspace=workspace)
            self.assertTrue(report['isolated_health'])
            self.assertTrue(report['original_server_unchanged'])
            self.assertEqual(report['modules_staged'], 1)
            self.assertEqual((source / "server.py").read_bytes(), ORIGINAL)
            self.assertEqual(list(workspace.iterdir()), [])
