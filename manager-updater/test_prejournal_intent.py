import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

from creative_release import Refused
from prejournal_intent import begin_attempt, recover_unjournaled


TICKET = b'a' * 64 + b'\n'
ID = 'b' * 32


def crash_before_journal(state, source):
    begin_attempt(state, source, TICKET, ID)
    os._exit(0)


class PrejournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rb-prejournal-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.state = root / 'state'
        self.state.mkdir(mode=0o700)
        self.source = root / 'source'
        self.source.mkdir()
        (self.source / 'server.py').write_bytes(b'guarded server fixture')
        (self.source / 'creative_engine.py').write_bytes(b'engine before')
        (self.state / 'update.lock').touch(mode=0o600)

    def test_killed_updater_before_first_journal_recovers_without_code_change(self):
        child = multiprocessing.get_context('spawn').Process(
            target=crash_before_journal, args=(self.state, self.source))
        child.start()
        child.join(5)
        if child.is_alive():
            child.terminate()
            child.join(5)
        self.assertEqual(child.exitcode, 0)
        self.assertTrue((self.state / 'maintenance.ticket').exists())
        self.assertFalse((self.state / 'transaction.json').exists())
        result = recover_unjournaled(self.state, self.source, TICKET, ID)
        self.assertEqual(result['state'], 'prejournal_recovered')
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), b'engine before')
        self.assertFalse((self.state / 'maintenance.ticket').exists())

    def test_code_change_journal_advance_or_active_server_keeps_marker(self):
        begin_attempt(self.state, self.source, TICKET, ID)
        engine = self.source / 'creative_engine.py'
        engine.write_bytes(b'unexpected edit')
        with self.assertRaises(Refused):
            recover_unjournaled(self.state, self.source, TICKET, ID)
        engine.write_bytes(b'engine before')
        (self.state / 'transaction.json').write_text('{"phase":"switch_pending"}')
        with self.assertRaises(Refused):
            recover_unjournaled(self.state, self.source, TICKET, ID)
        (self.state / 'transaction.json').unlink()
        fd = os.open(self.state / 'update.lock', os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            with self.assertRaisesRegex(Refused, 'server_still_running'):
                recover_unjournaled(self.state, self.source, TICKET, ID)
        finally:
            os.close(fd)
        self.assertTrue((self.state / 'maintenance.ticket').exists())

    def test_busy_http_refusal_cleans_only_unmarked_intent(self):
        fd = os.open(self.state / 'admission.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            with self.assertRaisesRegex(Refused, 'worker_busy_or_maintenance'):
                begin_attempt(self.state, self.source, TICKET, ID)
        finally:
            os.close(fd)
        self.assertFalse((self.state / 'maintenance.ticket').exists())
        self.assertFalse((self.state / 'maintenance-intent.json').exists())

    def test_prior_terminal_journal_is_bound_to_this_source_and_exact_bytes(self):
        journal = self.state / 'transaction.json'
        journal.write_text(json.dumps({'phase': 'committed', 'source': str(self.source),
                                       'id': 'c' * 32, 'sequence': 1}))
        journal.chmod(0o600)
        begin_attempt(self.state, self.source, TICKET, ID)
        journal.write_text(json.dumps({'phase': 'committed', 'source': str(self.source),
                                       'id': 'c' * 32, 'sequence': 2}))
        with self.assertRaises(Refused):
            recover_unjournaled(self.state, self.source, TICKET, ID)
        self.assertTrue((self.state / 'maintenance.ticket').exists())


if __name__ == '__main__':
    unittest.main()
