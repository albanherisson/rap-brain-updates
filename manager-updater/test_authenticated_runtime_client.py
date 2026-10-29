from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
import unittest

from authenticated_runtime_client import parse_response, read_runtime_proof
from creative_release import Refused


TOKEN = 'a' * 64


class ProofHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path != '/api/manager-update-proof' or self.headers.get('X-RB-Update-Token') != TOKEN:
            self.send_error(404)
            return
        raw = json.dumps({'parent_pid': 5100, 'worker_pid': 5101,
                          'audio_pid': None, 'worker_script_matches': True}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class RuntimeClientTests(unittest.TestCase):
    def test_local_authenticated_proof_binds_owned_parent(self):
        server = HTTPServer(('127.0.0.1', 0), ProofHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            port = server.server_address[1]
            self.assertEqual(read_runtime_proof(port, TOKEN, expected_parent_pid=5100)['worker_pid'], 5101)
            with self.assertRaisesRegex(Refused, 'identity_mismatch'):
                read_runtime_proof(port, TOKEN, expected_parent_pid=9999)
            with self.assertRaisesRegex(Refused, 'not_authenticated'):
                read_runtime_proof(port, 'b' * 64, expected_parent_pid=5100)
        finally:
            server.shutdown()
            worker.join(3)
            server.server_close()

    def test_duplicate_unknown_and_busy_report_refused(self):
        valid = b'{"parent_pid":5100,"worker_pid":5101,"audio_pid":null,"worker_script_matches":true}'
        for raw in (valid.replace(b'"parent_pid":5100', b'"parent_pid":5100,"parent_pid":5100'),
                    valid.replace(b'"audio_pid":null', b'"audio_pid":5102'),
                    valid.replace(b'"worker_script_matches":true', b'"worker_script_matches":false'),
                    valid[:-1] + b',"lyrics":"secret"}'):
            with self.subTest(raw=raw), self.assertRaises(Refused):
                parse_response(raw, expected_parent_pid=5100)


if __name__ == '__main__':
    unittest.main()
