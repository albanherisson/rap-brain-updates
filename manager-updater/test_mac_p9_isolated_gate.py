from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from mac_p9_isolated_gate import (
    CANDIDATE, EXPECTED, check_answer, run_isolated, sha, signed_candidate,
    verify_signature)


ROOT = Path(__file__).resolve().parents[1]
P8 = ROOT.parent / 'upload' / 'RapBrain_CreativeEngine_P8_Signed_Candidate.zip'
BOOTSTRAP = ROOT.parent / 'raw-guarded-1.zip'
REVIEW = ROOT.parent / 'library-downloads' / 'RapBrain_CreativeEngine_SourceReview.zip'


class P9GateTests(unittest.TestCase):
    def test_private_temp_path_has_no_symlink_ancestors(self):
        with tempfile.TemporaryDirectory(prefix='rapbrain-p9-isolated-') as tmp:
            root = Path(tmp).resolve(strict=True)
            self.assertFalse(any(path.is_symlink() for path in (root, *root.parents)))

    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS CryptoKit')
    def test_swift_fallback_verifies_without_python_crypto(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        message = b'{"disposable":true}'
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(sys.modules, {
                'cryptography.hazmat.primitives.asymmetric.ed25519': None}):
                verify_signature(public, key.sign(message), message, Path(temp))
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_signed_p8_candidate_is_exact_and_still_non_installable(self):
        if not P8.is_file():
            self.skipTest('owner P8 attachment unavailable in checkout')
        with tempfile.TemporaryDirectory() as temp:
            with patch('mac_p9_isolated_gate.PACKAGE', P8):
                self.assertEqual(sha(signed_candidate(Path(temp))), CANDIDATE)

    def test_result_requires_four_bars_and_synthetic_source(self):
        answer = {'answer': 'One two three four five\n' * 4,
                  'rag_sources': [{'artist': 'Synthetic Fixture'}]}
        self.assertEqual(check_answer(answer), (4, 1))
        with self.assertRaisesRegex(ValueError, 'creative_wrong_bar_count_0'):
            check_answer({**answer, 'answer': ''})
        with self.assertRaisesRegex(ValueError, 'creative_synthetic_rag_missing'):
            check_answer({**answer, 'rag_sources': []})

    @unittest.skipUnless(P8.is_file() and BOOTSTRAP.is_file() and REVIEW.is_file(),
                         'owner inputs unavailable in checkout')
    def test_full_disposable_server_uses_p8_rag_and_think_false(self):
        from mac_p9_isolated_gate import seed_fixture

        requests = []
        bars = ('I keep a paper map beneath the lighthouse glow\n'
                'A folded road reminds me where the tides may go\n'
                'I mark the shoreline twice before I choose my way\n'
                'The beacon finds my footsteps at the break of day')

        class FakeOllama(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                raw = json.dumps({'models': [{'name': 'qwen3.5:27b'}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(body)
                count = len(requests)
                content = ('{"narrative_beats": ["lighthouse", "decision"]}' if count == 1 else
                           bars if count == 2 else
                           '{"pass": true, "issues": [], "multisyllabic_pairs": []}')
                raw = json.dumps({'message': {'content': content}}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(raw)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'home'
            stage = home / 'Downloads' / 'rap-brain'
            stage.mkdir(parents=True)
            with ZipFile(BOOTSTRAP) as bootstrap, ZipFile(REVIEW) as review:
                server = bootstrap.read('server.py')
                rag = review.read('code/creative_rag.py')
                validator = review.read('code/rhyme_validator.py')
            with patch('mac_p9_isolated_gate.PACKAGE', P8):
                candidate = signed_candidate(root)
            for name, raw in [('server.py', server), ('creative_engine.py', candidate),
                              ('creative_rag.py', rag), ('rhyme_validator.py', validator)]:
                if name in EXPECTED:
                    self.assertEqual(sha(raw), CANDIDATE if name == 'creative_engine.py'
                                     else EXPECTED[name])
                (stage / name).write_bytes(raw)
            data = stage / 'data'
            data.mkdir()
            (data / 'ollama_model.json').write_text('{"model":"qwen3.5:27b"}')
            ollama = ThreadingHTTPServer(('127.0.0.1', 0), FakeOllama)
            thread = threading.Thread(target=ollama.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertEqual(run_isolated(stage, home,
                    ollama_url=f'http://127.0.0.1:{ollama.server_port}',
                    listener_check=lambda _port, _pid: True), (4, 1))
            finally:
                ollama.shutdown()
                ollama.server_close()
                thread.join(timeout=3)
        self.assertGreaterEqual(len(requests), 3)
        self.assertTrue(all(request['think'] is False and
                            request['model'] == 'qwen3.5:27b' for request in requests))
        self.assertIn('lighthouse scene', requests[0]['messages'][-1]['content'].lower())


if __name__ == '__main__':
    unittest.main()
