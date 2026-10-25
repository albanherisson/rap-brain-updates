"""Owned-child HTTP restart + transactional rollback integration (disposable only).

No real app, persistent service, production PID, or external localhost port is targeted.
"""
import tempfile
import unittest
from pathlib import Path
from external_supervisor_fixture import MARKER, run
from fixture_restart_lab import SERVER, free_port, launch, stop, healthy

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="rapbrain-supervisor-lab-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"DisposableSupervisorFixture"
        self.root.mkdir()
        (self.root/"fixture.marker").write_bytes(MARKER)
        (self.root/"manager.txt").write_bytes(b"VERSION_A")
        (self.root/"candidate.txt").write_bytes(b"VERSION_B")
        self.server_path=self.root/"dummy_http.py"
        self.server_path.write_text(SERVER)
        self.port=free_port()

    def test_restart_success_with_real_owned_child(self):
        first=launch(self.server_path,self.port)
        try:
            self.assertTrue(healthy(self.port))
            stop(first)
            self.assertIsNotNone(first.poll())
            self.assertEqual(run(self.root,health=True),"COMMITTED")
            second=launch(self.server_path,self.port)
            try:
                self.assertTrue(healthy(self.port))
                self.assertNotEqual(first.pid,second.pid)
                self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_B")
            finally:
                stop(second)
        finally:
            stop(first)

    def test_failed_health_rolls_back_fixture(self):
        first=launch(self.server_path,self.port)
        try:
            self.assertTrue(healthy(self.port))
            stop(first)
            self.assertEqual(run(self.root,health=False),"ROLLED_BACK")
            self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_A")
            restored=launch(self.server_path,self.port)
            try:
                self.assertTrue(healthy(self.port))
            finally:
                stop(restored)
        finally:
            stop(first)

if __name__=="__main__":
    unittest.main()
