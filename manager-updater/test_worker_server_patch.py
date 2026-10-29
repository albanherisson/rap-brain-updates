import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from server_worker_activity_candidate import prepare_worker_activity


FIXTURE = b'''from http.server import BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        return None
    def do_POST(self):
        try:
            return None
        except Exception:
            return None
calls = []
def job_runner(job_id, track_id):
    calls.append((job_id, track_id))
def worker_main():
    calls.append('worker_started')
if __name__ == '__main__':
    worker_main()
'''


class WorkerPatchTests(unittest.TestCase):
    def test_marker_refuses_job_and_worker_start_then_allows_after_removal(self):
        output = prepare_worker_activity(FIXTURE, hashlib.sha256(FIXTURE).hexdigest())
        scope = {'__name__': 'fixture'}
        exec(output, scope)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            home = Path(temp) / 'home'
            state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
            state.mkdir(parents=True, mode=0o700)
            old_home = os.environ.get('HOME')
            try:
                os.environ['HOME'] = str(home)
                scope['job_runner'](1, 2)
                self.assertEqual(scope['calls'], [(1, 2)])
                marker = state / 'maintenance.ticket'
                marker.write_bytes(b'a' * 64 + b'\n')
                with self.assertRaisesRegex(RuntimeError, 'maintenance_in_progress'):
                    scope['job_runner'](3, 4)
                self.assertEqual(scope['calls'], [(1, 2)])
                marker.unlink()
                scope['worker_main']()
                self.assertEqual(scope['calls'][-1], 'worker_started')
            finally:
                if old_home is None:
                    os.environ.pop('HOME', None)
                else:
                    os.environ['HOME'] = old_home

    def test_unknown_worker_shape_refused(self):
        missing = FIXTURE.replace(b'def worker_main():', b'def unrelated():')
        with self.assertRaisesRegex(ValueError, 'unsupported_worker_flow'):
            prepare_worker_activity(missing, hashlib.sha256(missing).hexdigest())


if __name__ == '__main__':
    unittest.main()
