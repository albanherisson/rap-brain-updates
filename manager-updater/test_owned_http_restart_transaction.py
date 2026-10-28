"""Owned-child HTTP restart + transactional rollback integration (disposable only).

No real app, persistent service, production PID, or external localhost port is targeted.
"""
import tempfile
import unittest
from pathlib import Path
from external_supervisor_fixture import MARKER, run
from fixture_restart_lab import SERVER, free_port, stop
import socket
import subprocess
import sys
import time

def healthy(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=1):
            return True
    except OSError:
        return False

def launch(script,port):
    child=subprocess.Popen([sys.executable,str(script),str(port)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(100):
        if child.poll() is not None:break
        if healthy(port):return child
        time.sleep(.05)
    stop(child)
    raise RuntimeError('owned dummy failed TCP readiness')

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
