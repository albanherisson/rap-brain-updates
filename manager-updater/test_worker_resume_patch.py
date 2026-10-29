import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from server_worker_resume_candidate import prepare_worker_activity
from test_worker_server_patch import FIXTURE


RESUME_FIXTURE = FIXTURE.replace(
    b'def worker_main():\n',
    b'def resume_jobs():\n    calls.append("resumed")\ndef worker_main():\n    resume_jobs()\n')
PROOF_FIXTURE = RESUME_FIXTURE.replace(
    b'class Handler(BaseHTTPRequestHandler):\n',
    b'class Handler(BaseHTTPRequestHandler):\n'
    b'    def send(self, value, status=200):\n        return value, status\n')
PROOF_FIXTURE = PROOF_FIXTURE.replace(
    b'calls = []\n',
    b'calls = []\nAUDIO_LOCK = __import__("threading").Lock()\n'
    b'AUDIO_STATE = {"process": None}\nWORKER_PROCESS = None\n')


class WorkerResumeTests(unittest.TestCase):
    def test_resume_is_blocked_by_marker_then_allowed(self):
        candidate = prepare_worker_activity(
            RESUME_FIXTURE, hashlib.sha256(RESUME_FIXTURE).hexdigest())
        scope = {'__name__': 'fixture'}
        exec(candidate, scope)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            home = Path(temp) / 'home'
            state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
            state.mkdir(parents=True, mode=0o700)
            old_home = os.environ.get('HOME')
            try:
                os.environ['HOME'] = str(home)
                marker = state / 'maintenance.ticket'
                marker.write_bytes(b'a' * 64 + b'\n')
                with self.assertRaisesRegex(RuntimeError, 'maintenance_in_progress'):
                    scope['resume_jobs']()
                self.assertEqual(scope['calls'], [])
                marker.unlink()
                scope['worker_main']()
                self.assertEqual(scope['calls'], ['resumed', 'worker_started'])
            finally:
                if old_home is None:
                    os.environ.pop('HOME', None)
                else:
                    os.environ['HOME'] = old_home

    def test_unknown_resume_flow_refused(self):
        with self.assertRaisesRegex(ValueError, 'unsupported_worker_flow'):
            prepare_worker_activity(FIXTURE, hashlib.sha256(FIXTURE).hexdigest())

    def test_runtime_proof_requires_launch_token_and_reports_only_process_ids(self):
        candidate = prepare_worker_activity(
            PROOF_FIXTURE, hashlib.sha256(PROOF_FIXTURE).hexdigest())
        scope = {'__name__': 'fixture'}
        exec(candidate, scope)
        handler = scope['Handler'].__new__(scope['Handler'])
        handler.path = '/api/manager-update-proof'
        handler.headers = {'X-RB-Update-Token': 'a' * 64}
        old = os.environ.get('RB_UPDATE_PROBE_TOKEN')
        try:
            os.environ['RB_UPDATE_PROBE_TOKEN'] = 'a' * 64
            report, status = handler.do_GET()
            self.assertEqual(status, 200)
            self.assertEqual(report, {'parent_pid': os.getpid(),
                                      'worker_pid': None, 'audio_pid': None})
            handler.headers['X-RB-Update-Token'] = 'b' * 64
            self.assertEqual(handler.do_GET()[1], 404)
        finally:
            if old is None:
                os.environ.pop('RB_UPDATE_PROBE_TOKEN', None)
            else:
                os.environ['RB_UPDATE_PROBE_TOKEN'] = old


if __name__ == '__main__':
    unittest.main()
