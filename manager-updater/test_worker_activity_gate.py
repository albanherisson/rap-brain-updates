import multiprocessing
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest

from creative_release import Refused
from worker_activity_gate import JobLease, begin_maintenance, finish_maintenance


TICKET = b'a' * 64 + b'\n'
TRANSACTION_ID = 'c' * 32


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

    def test_in_flight_http_request_refuses_maintenance_before_marker(self):
        fd = os.open(self.path / 'admission.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            with self.assertRaisesRegex(Refused, 'worker_busy_or_maintenance'):
                begin_maintenance(self.path, TICKET)
            self.assertFalse((self.path / 'maintenance.ticket').exists())
        finally:
            os.close(fd)
        begin_maintenance(self.path, TICKET)

    def test_marker_survives_crash_state_and_only_terminal_healthy_owner_releases(self):
        begin_maintenance(self.path, TICKET)
        journal = self.path / 'transaction.json'
        journal.write_text(json.dumps({'id': TRANSACTION_ID, 'phase': 'switched'}))
        journal.chmod(0o600)
        with self.assertRaisesRegex(Refused, 'transaction_not_terminal'):
            finish_maintenance(self.path, TICKET, expected_transaction_id=TRANSACTION_ID,
                               owned_health_verified=True)
        journal.write_text(json.dumps({'id': TRANSACTION_ID, 'phase': 'committed'}))
        with self.assertRaisesRegex(Refused, 'transaction_not_terminal'):
            finish_maintenance(self.path, TICKET, expected_transaction_id='d' * 32,
                               owned_health_verified=True)
        for ticket, health in ((b'b' * 64 + b'\n', True), (TICKET, False)):
            with self.assertRaises(Refused):
                finish_maintenance(self.path, ticket, expected_transaction_id=TRANSACTION_ID,
                                   owned_health_verified=health)
        self.assertTrue((self.path / 'maintenance.ticket').exists())
        finish_maintenance(self.path, TICKET, expected_transaction_id=TRANSACTION_ID,
                           owned_health_verified=True)
        self.assertFalse((self.path / 'maintenance.ticket').exists())
        with JobLease(self.path):
            pass

    def test_duplicate_or_malformed_journal_never_releases_marker(self):
        begin_maintenance(self.path, TICKET)
        journal = self.path / 'transaction.json'
        journal.touch(mode=0o600)
        journal.chmod(0o600)
        for raw in ('{"id":"' + TRANSACTION_ID + '","phase":"switched","phase":"committed"}', '{oops'):
            journal.write_text(raw)
            with self.assertRaises(Refused):
                finish_maintenance(self.path, TICKET, expected_transaction_id=TRANSACTION_ID,
                                   owned_health_verified=True)
            self.assertTrue((self.path / 'maintenance.ticket').exists())


if __name__ == '__main__':
    unittest.main()
