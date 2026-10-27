import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from server_lifetime_guard import prepare, prepare_copy

FIXTURE = b'''import os
import time
if __name__ == '__main__':
    print('READY', flush=True)
    time.sleep(0.6)
'''


class LifetimeGuardTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
