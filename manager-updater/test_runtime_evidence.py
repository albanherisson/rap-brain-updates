import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from creative_release import Refused
from runtime_evidence import collect_owned_idle_proof
from worker_activity_gate import _lock


class Child:
    pid = 5100

    def __init__(self, script):
        self.args = ['python3', str(script)]

    def poll(self):
        return None


class EvidenceTests(unittest.TestCase):
    def test_owned_snapshot_drains_locks_and_refuses_busy_or_changed_jobs(self):
        # macOS /var is a symlink to /private/var; production deliberately
        # rejects symlink parents. Place this disposable fixture under checkout.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            source = root / 'source'
            data = source / 'data'
            data.mkdir(parents=True)
            state = root / 'private'
            state.mkdir(mode=0o700)
            script = source / 'server.py'
            script.write_bytes(b'# pinned fixture\n')
            expected = hashlib.sha256(script.read_bytes()).hexdigest()
            db = data / 'rapbrain.sqlite3'
            with sqlite3.connect(db) as con:
                con.execute('CREATE TABLE jobs (status TEXT NOT NULL)')
                con.execute("INSERT INTO jobs VALUES ('done')")
            ticket = b'a' * 64 + b'\n'
            (state / 'maintenance.ticket').write_bytes(ticket)
            (state / 'maintenance.ticket').chmod(0o600)
            handle = Child(script)
            start = '5100:Tue Oct 27 21:36:22 2026'
            kwargs = dict(source=source, state=state, handle=handle,
                          recorded_start=start, recorded_server_sha256=expected,
                          token='b' * 64, ticket=ticket, port=8765)
            report = dict(parent_pid=5100, worker_pid=5101, audio_pid=None,
                          worker_script_matches=True)
            with (patch('runtime_evidence.require_live_owned_handle', return_value=start),
                  patch('runtime_evidence.read_runtime_proof', return_value=report),
                  patch('runtime_evidence.read_owned_group',
                        return_value=frozenset((5100, 5101))) as group,
                  patch('runtime_evidence.read_start',
                        return_value='5101:Tue Oct 27 21:36:23 2026')):
                proof = collect_owned_idle_proof(**kwargs)
                self.assertEqual(proof.job_status_counts, {'done': 1})
                group.assert_called_once_with(manager_pid=os.getpid(),
                                              parent_pid=5100, worker_pid=5101)
                held = _lock(state, 'worker-job.lock', fcntl.LOCK_SH)
                try:
                    with self.assertRaisesRegex(Refused, 'worker_busy'):
                        collect_owned_idle_proof(**kwargs)
                finally:
                    os.close(held)
                with sqlite3.connect(db) as con:
                    con.execute("INSERT INTO jobs VALUES ('queued')")
                with self.assertRaisesRegex(Refused, 'jobs_active'):
                    collect_owned_idle_proof(**kwargs)
                with sqlite3.connect(db) as con:
                    con.execute("DELETE FROM jobs WHERE status='queued'")
                with patch('runtime_evidence.read_runtime_proof',
                           return_value=dict(report, audio_pid=5102)):
                    with self.assertRaisesRegex(Refused, 'audio_capture'):
                        collect_owned_idle_proof(**kwargs)


if __name__ == '__main__':
    unittest.main()
