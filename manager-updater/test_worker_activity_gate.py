import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

from creative_release import Refused
from worker_activity_gate import JobLease, begin_maintenance


TICKET = b'a' * 64 + b'\n'


def running_job(path, ready, release):
    with JobLease(path):
        ready.set()
        release.wait(10)


class WorkerGateTests(unittest.TestCase):
    def setUp(self):
        # macOS /var is a symlink to /private/var; the production gate must
        # refuse it. Put this disposable fixture under the checkout instead.
        self.temp = tempfile.TemporaryDirectory(prefix='rb-worker-gate-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_running_job_refuses_maintenance_then_marker_refuses_next_job(self):
        context = multiprocessing.get_context('spawn')
        ready, release = context.Event(), context.Event()
        child = context.Process(target=running_job, args=(self.path, ready, release))
        child.start()
        try:
            self.assertTrue(ready.wait(5))
            with self.assertRaisesRegex(Refused, 'worker_busy'):
                begin_maintenance(self.path, TICKET)
            self.assertFalse((self.path / 'maintenance.ticket').exists())
        finally:
            release.set()
            child.join(5)
            if child.is_alive():
                child.terminate()
                child.join(5)
        self.assertEqual(child.exitcode, 0)
        begin_maintenance(self.path, TICKET)
        with self.assertRaisesRegex(Refused, 'maintenance_in_progress'):
            with JobLease(self.path):
                self.fail('A job started during maintenance')

    def test_existing_marker_and_unsafe_state_fail_closed(self):
        begin_maintenance(self.path, TICKET)
        with self.assertRaises(FileExistsError):
            begin_maintenance(self.path, TICKET)
        self.path.chmod(0o755)
        with self.assertRaisesRegex(Refused, 'private_worker_gate'):
            with JobLease(self.path):
                self.fail('An unsafe gate admitted a job')
        self.path.chmod(0o700)


if __name__ == '__main__':
    unittest.main()
