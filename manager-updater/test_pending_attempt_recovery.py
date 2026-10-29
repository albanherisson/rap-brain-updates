import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest

from creative_release import Refused
from pending_attempt_recovery import acquire_stopped_attempt
from prejournal_intent import begin_attempt


TICKET = b'a' * 64 + b'\n'
IDENTIFIER = 'b' * 32


class PendingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rb-pending-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'source'
        self.source.mkdir()
        (self.source / 'server.py').write_bytes(b'guarded-server-fixture')
        (self.source / 'creative_engine.py').write_bytes(b'baseline-fixture')
        self.state = root / 'state'
        self.state.mkdir(mode=0o700)
        (self.state / 'update.lock').touch(mode=0o600)
        begin_attempt(self.state, self.source, TICKET, IDENTIFIER)
        self.journal = self.state / 'transaction.json'
        self.journal.write_text(json.dumps({'id': IDENTIFIER,
            'source': str(self.source), 'phase': 'switched'}))
        self.journal.chmod(0o600)

    def acquire(self, identifier=IDENTIFIER, listener_absent=lambda: True):
        return acquire_stopped_attempt(self.source, self.state, identifier,
                                       listener_absent=listener_absent)

    def test_original_ticket_and_stopped_writers_only(self):
        attempt = self.acquire()
        self.assertEqual(attempt.ticket, TICKET)
        self.assertEqual(attempt.transaction_id, IDENTIFIER)
        attempt.assert_stopped()
        attempt.close()
        self.assertTrue((self.state / 'maintenance.ticket').exists())
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(),
                         b'baseline-fixture')

    def test_guarded_writer_listener_or_changed_attempt_refuses(self):
        fd = os.open(self.state / 'update.lock', os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            with self.assertRaisesRegex(Refused, 'guarded_writers_still_running'):
                self.acquire()
        finally:
            os.close(fd)
        with self.assertRaisesRegex(Refused, 'local_listener_still_present_or_unknown'):
            self.acquire(listener_absent=lambda: False)
        with self.assertRaisesRegex(Refused, 'recovery_attempt_mismatch'):
            self.acquire('c' * 32)
        self.journal.write_text(json.dumps({'id': IDENTIFIER,
            'source': str(self.source), 'phase': 'committed'}))
        with self.assertRaisesRegex(Refused, 'recovery_attempt_mismatch'):
            self.acquire()
        self.assertTrue((self.state / 'maintenance.ticket').exists())


if __name__ == '__main__':
    unittest.main()
