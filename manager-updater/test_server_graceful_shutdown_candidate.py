import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from server_graceful_shutdown_candidate import prepare
from test_worker_resume_patch import PROOF_FIXTURE


class Worker:
    pid = 5200

    def __init__(self):
        self.args = [sys.executable, str(Path(__file__).resolve()), '--worker']

    def poll(self):
        return None


class Server:
    def __init__(self):
        self.stopped = threading.Event()

    def shutdown(self):
        self.stopped.set()


class StopCandidateTests(unittest.TestCase):
    def test_stop_requires_owned_token_ticket_idle_worker_and_no_audio(self):
        candidate = prepare(PROOF_FIXTURE,
                            hashlib.sha256(PROOF_FIXTURE).hexdigest())
        scope = {'__name__': 'fixture', '__file__': str(Path(__file__).resolve())}
        exec(candidate, scope)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            home = Path(temp) / 'home'
            state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
            state.mkdir(parents=True, mode=0o700)
            marker = state / 'maintenance.ticket'
            marker.write_bytes(b'b' * 64 + b'\n')
            marker.chmod(0o600)
            server = Server()
            handler = scope['Handler'].__new__(scope['Handler'])
            handler.server = server
            handler.path = '/api/manager-update-stop'
            handler.headers = {'X-RB-Update-Token': 'a' * 64,
                               'X-RB-Update-Ticket': 'b' * 64}
            old_home = os.environ.get('HOME')
            old_token = os.environ.get('RB_UPDATE_PROBE_TOKEN')
            try:
                os.environ['HOME'] = str(home)
                os.environ['RB_UPDATE_PROBE_TOKEN'] = 'a' * 64
                scope['WORKER_PROCESS'] = Worker()
                handler.headers['X-RB-Update-Ticket'] = 'c' * 64
                self.assertEqual(handler.do_POST()[1], 503)
                self.assertFalse(server.stopped.is_set())
                handler.headers['X-RB-Update-Ticket'] = 'b' * 64
                handler.headers['X-RB-Update-Token'] = 'c' * 64
                self.assertEqual(handler.do_POST()[1], 404)
                handler.headers['X-RB-Update-Token'] = 'a' * 64
                scope['AUDIO_STATE']['process'] = Worker()
                self.assertEqual(handler.do_POST()[1], 503)
                scope['AUDIO_STATE']['process'] = None
                self.assertEqual(handler.do_POST(), ({'stopping': True}, 202))
                self.assertTrue(server.stopped.wait(2))
            finally:
                if old_home is None:
                    os.environ.pop('HOME', None)
                else:
                    os.environ['HOME'] = old_home
                if old_token is None:
                    os.environ.pop('RB_UPDATE_PROBE_TOKEN', None)
                else:
                    os.environ['RB_UPDATE_PROBE_TOKEN'] = old_token


if __name__ == '__main__':
    unittest.main()
