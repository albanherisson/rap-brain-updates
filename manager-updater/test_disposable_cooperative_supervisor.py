import tempfile
import unittest
from pathlib import Path
from external_supervisor_fixture import MARKER
from disposable_cooperative_supervisor import DummyServer,Rejected,fixture_transaction
SECRET=b"fixture-test-secret-that-is-not-a-production-key"

class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)/"DisposableSupervisorFixture";self.root.mkdir()
  (self.root/"fixture.marker").write_bytes(MARKER)
  (self.root/"manager.txt").write_bytes(b"VERSION_A")
  (self.root/"candidate.txt").write_bytes(b"VERSION_B")
 def test_healthy_transaction(self):
  server=DummyServer(SECRET)
  self.assertEqual(fixture_transaction(self.root,server,SECRET),"COMMITTED")
  self.assertFalse(server.alive)
 def test_wrong_key_blocks_before_stop(self):
  server=DummyServer(SECRET)
  with self.assertRaises(Rejected):fixture_transaction(self.root,server,b"z"*32)
  self.assertTrue(server.alive)
  self.assertFalse((self.root/"journal.json").exists())
 def test_unsigned_blocks_before_stop(self):
  server=DummyServer(SECRET)
  with self.assertRaises(Rejected):fixture_transaction(self.root,server,SECRET,signed=False)
  self.assertTrue(server.alive)
 def test_health_failure_rolls_back(self):
  server=DummyServer(SECRET)
  self.assertEqual(fixture_transaction(self.root,server,SECRET,health=False),"ROLLED_BACK")
  self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_A")
 def test_replayed_stop_fails(self):
  server=DummyServer(SECRET);server.cooperative_stop(b"x"*32,server.response(b"x"*32))
  with self.assertRaises(Rejected):server.cooperative_stop(b"x"*32,b"z"*32)
 def test_wrong_directory_refused(self):
  with self.assertRaises(Rejected):fixture_transaction(self.root.parent,DummyServer(SECRET),SECRET)
 def test_interrupted_recovers_with_fixture_only(self):
  server=DummyServer(SECRET)
  with self.assertRaises(RuntimeError):fixture_transaction(self.root,server,SECRET,crash="switched")
  from external_supervisor_fixture import run
  self.assertEqual(run(self.root),"RECOVERED_OLD")
  self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_A")
if __name__=="__main__":unittest.main()
