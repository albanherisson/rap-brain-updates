import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from server_lifetime_guard import prepare, prepare_admission, prepare_copy

FIXTURE = b'''import os
import time
if __name__ == '__main__':
    print('READY', flush=True)
    time.sleep(0.6)
'''

HTTP_FIXTURE = b'''from http.server import BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
    def send(self, data, status=200):
        return data, status
    def do_GET(self):
        return self.send({'healthy': True})
    def do_POST(self):
        try:
            return self.send({'created': True}, 200)
        except Exception:
            return self.send({'error': True}, 500)
if __name__ == '__main__':
    print('READY', flush=True)
'''


class LifetimeGuardTests(unittest.TestCase):
    def test_maintenance_blocks_all_posts_but_preserves_health_get(self):
        output = prepare_admission(HTTP_FIXTURE, hashlib.sha256(HTTP_FIXTURE).hexdigest())
        namespace = {'__name__': 'fixture'}
        exec(output, namespace)
        handler = namespace['Handler'].__new__(namespace['Handler'])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            home = root / 'home'
            home.mkdir()
            old_home = os.environ.get('HOME')
            try:
                os.environ['HOME'] = str(home)
                state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
                state.mkdir(parents=True, mode=0o700)
                self.assertEqual(handler.do_POST()[1], 200)
                (state / 'maintenance.ticket').write_text('a' * 64 + '\n')
                self.assertEqual(handler.do_POST(), ({'error': 'update_in_progress'}, 503))
                self.assertEqual(handler.do_GET(), ({'healthy': True}, 200))
            finally:
                if old_home is None:
                    os.environ.pop('HOME', None)
                else:
                    os.environ['HOME'] = old_home

    def test_in_flight_post_holds_admission_lock_until_finished(self):
        fixture = HTTP_FIXTURE.replace(
            b"return self.send({'created': True}, 200)",
            b"self.entered.set(); self.resume.wait(5); return self.send({'created': True}, 200)")
        namespace = {'__name__': 'fixture'}
        exec(prepare_admission(fixture, hashlib.sha256(fixture).hexdigest()), namespace)
        handler = namespace['Handler'].__new__(namespace['Handler'])
        handler.entered = threading.Event()
        handler.resume = threading.Event()
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp).resolve() / 'home'
            home.mkdir()
            old_home = os.environ.get('HOME')
            try:
                os.environ['HOME'] = str(home)
                state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
                state.mkdir(parents=True, mode=0o700)
                thread = threading.Thread(target=handler.do_POST)
                thread.start()
                self.assertTrue(handler.entered.wait(5))
                fd = os.open(state / 'admission.lock', os.O_RDWR | os.O_NOFOLLOW)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    handler.resume.set()
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    (state / 'maintenance.ticket').write_text('a' * 64 + '\n')
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    self.assertEqual(handler.do_POST()[1], 503)
                finally:
                    handler.resume.set()
                    thread.join(5)
                    os.close(fd)
            finally:
                if old_home is None:
                    os.environ.pop('HOME', None)
                else:
                    os.environ['HOME'] = old_home

    def test_post_gate_requires_known_handler_shape(self):
        with self.assertRaisesRegex(ValueError, 'unsupported_http_handler'):
            prepare_admission(FIXTURE, hashlib.sha256(FIXTURE).hexdigest())

    def test_unknown_source_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'unknown_server_baseline'):
            prepare(FIXTURE)

    def test_only_guard_is_inserted_and_copy_is_separate(self):
        output = prepare(FIXTURE, hashlib.sha256(FIXTURE).hexdigest())
        self.assertIn(FIXTURE.splitlines()[0], output.splitlines())
        self.assertIn(b"print('READY', flush=True)", output)
        with self.assertRaisesRegex(ValueError, 'already_patched'):
            prepare(output, hashlib.sha256(output).hexdigest())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / 'live' / 'server.py'
            source.parent.mkdir()
            source.write_bytes(FIXTURE)
            with self.assertRaisesRegex(ValueError, 'unknown_server_baseline'):
                prepare_copy(source, root / 'staging' / 'server.py')
            self.assertEqual(source.read_bytes(), FIXTURE)

    def test_server_lifetime_shared_lock_blocks_exclusive_updater_and_new_start(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            home = root / 'home'
            home.mkdir()
            script = root / 'server.py'
            script.write_bytes(prepare(FIXTURE, hashlib.sha256(FIXTURE).hexdigest()))
            env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
            one = subprocess.Popen([sys.executable, '-B', str(script)], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(one.stdout.readline().strip(), 'READY')
                lock = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update' / 'update.lock'
                fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    one.wait(timeout=5)
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    blocked = subprocess.run([sys.executable, '-B', str(script)], env=env,
                                             capture_output=True, text=True, timeout=5)
                    self.assertNotEqual(blocked.returncode, 0)
                    self.assertNotIn('READY', blocked.stdout)
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                restarted = subprocess.run([sys.executable, '-B', str(script)], env=env,
                                           capture_output=True, text=True, timeout=5)
                self.assertEqual(restarted.returncode, 0, restarted.stderr)
                self.assertIn('READY', restarted.stdout)
            finally:
                if one.poll() is None:
                    one.terminate()
                    one.wait(timeout=5)
                one.stdout.close()
                one.stderr.close()

    def test_durable_maintenance_ticket_excludes_unrelated_launches(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            home = root / 'home'
            home.mkdir()
            script = root / 'server.py'
            script.write_bytes(prepare(FIXTURE, hashlib.sha256(FIXTURE).hexdigest()))
            env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
            # First boot creates the private lock directory. The external
            # updater would write the marker only after verified shutdown
            # while holding this lock exclusively.
            self.assertEqual(subprocess.run([sys.executable, '-B', str(script)], env=env,
                                            capture_output=True, timeout=5).returncode, 0)
            state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
            fd = os.open(state / 'update.lock', os.O_RDWR | os.O_NOFOLLOW)
            ticket = 'a' * 64
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                marker = state / 'maintenance.ticket'
                with marker.open('xb') as stream:
                    stream.write((ticket + '\n').encode())
                os.chmod(marker, 0o600)
                fcntl.flock(fd, fcntl.LOCK_UN)
                for offered in (None, 'b' * 64):
                    trial_env = dict(env)
                    if offered is None:
                        trial_env.pop('RB_UPDATE_LAUNCH_TICKET', None)
                    else:
                        trial_env['RB_UPDATE_LAUNCH_TICKET'] = offered
                    result = subprocess.run([sys.executable, '-B', str(script)], env=trial_env,
                                            capture_output=True, text=True, timeout=5)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('READY', result.stdout)
                candidate_env = dict(env, RB_UPDATE_LAUNCH_TICKET=ticket)
                candidate = subprocess.Popen([sys.executable, '-B', str(script)], env=candidate_env,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    self.assertEqual(candidate.stdout.readline().strip(), 'READY')
                    self.assertNotEqual(subprocess.run([sys.executable, '-B', str(script)], env=env,
                                                       capture_output=True, timeout=5).returncode, 0)
                    candidate.wait(timeout=5)
                finally:
                    if candidate.poll() is None:
                        candidate.terminate()
                        candidate.wait(timeout=5)
                    candidate.stdout.close()
                    candidate.stderr.close()
                # A crash leaves the marker in place and normal startup
                # blocked until the external transaction recovers.
                self.assertNotEqual(subprocess.run([sys.executable, '-B', str(script)], env=env,
                                                   capture_output=True, timeout=5).returncode, 0)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                marker.unlink()
                fcntl.flock(fd, fcntl.LOCK_UN)
                self.assertEqual(subprocess.run([sys.executable, '-B', str(script)], env=env,
                                                capture_output=True, timeout=5).returncode, 0)
            finally:
                os.close(fd)

    def test_malformed_marker_refuses_even_matching_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            home = root / 'home'
            home.mkdir()
            script = root / 'server.py'
            script.write_bytes(prepare(FIXTURE, hashlib.sha256(FIXTURE).hexdigest()))
            env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE='1',
                       RB_UPDATE_LAUNCH_TICKET='a' * 64)
            self.assertEqual(subprocess.run([sys.executable, '-B', str(script)], env=env,
                                            capture_output=True, timeout=5).returncode, 0)
            marker = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update' / 'maintenance.ticket'
            marker.write_text('bad\n')
            os.chmod(marker, 0o600)
            result = subprocess.run([sys.executable, '-B', str(script)], env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('READY', result.stdout)


if __name__ == '__main__':
    unittest.main()
