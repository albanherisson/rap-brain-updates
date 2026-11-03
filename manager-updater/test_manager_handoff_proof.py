"""Exact parent-exit proof from a private pipe; no real process signals."""
import hashlib
import os
import subprocess
import unittest
from unittest.mock import patch

from creative_release import Refused
from manager_handoff_proof import parent_has_exited, wait_for_parent_exit


class ParentHandoffProofTest(unittest.TestCase):
    START = '42:Fri Oct 30 12:01:02 2026'

    def pipe(self, raw):
        reader, writer = os.pipe()
        os.write(writer, raw)
        os.close(writer)
        return reader

    def test_valid_nonce_and_absent_parent(self):
        nonce = b'a' * 32
        with patch('manager_handoff_proof.subprocess.run',
                   return_value=subprocess.CompletedProcess([], 1, '', '')):
            self.assertTrue(wait_for_parent_exit(
                self.pipe(nonce), hashlib.sha256(nonce).hexdigest(),
                42, self.START, timeout=1))

    def test_wrong_nonce_refuses_even_if_parent_absent(self):
        with patch('manager_handoff_proof.subprocess.run') as ps:
            with self.assertRaises(Refused):
                wait_for_parent_exit(self.pipe(b'b' * 32),
                    hashlib.sha256(b'a' * 32).hexdigest(), 42,
                    self.START, timeout=1)
            ps.assert_not_called()

    def test_extra_pipe_bytes_refuse(self):
        with self.assertRaises(Refused):
            wait_for_parent_exit(self.pipe(b'a' * 33),
                hashlib.sha256(b'a' * 32).hexdigest(), 42,
                self.START, timeout=1)

    def test_live_parent_refuses(self):
        alive = subprocess.CompletedProcess([], 0,
            'Fri Oct 30 12:01:02 2026\n', '')
        with (patch('manager_handoff_proof.subprocess.run', return_value=alive),
              patch('manager_handoff_proof.time.sleep')):
            with self.assertRaises(Refused):
                wait_for_parent_exit(self.pipe(b'a' * 32),
                    hashlib.sha256(b'a' * 32).hexdigest(), 42,
                    self.START, timeout=0.01)

    def test_pid_reuse_counts_as_original_exit(self):
        reused = subprocess.CompletedProcess([], 0,
            'Fri Oct 30 12:02:02 2026\n', '')
        with patch('manager_handoff_proof.subprocess.run', return_value=reused):
            self.assertTrue(parent_has_exited(42, self.START))


if __name__ == '__main__':
    unittest.main()
