"""Exercise lifecycle policy and external transaction fixture together; disposable data ONLY."""
from pathlib import Path
import tempfile
import unittest
from mac_lifecycle_policy import Stage, simulate, plan
from external_supervisor_fixture import MARKER,run

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.root=Path(self.tmp.name)/"DisposableSupervisorFixture"
  self.root.mkdir()
  (self.root/"fixture.marker").write_bytes(MARKER)
  (self.root/"manager.txt").write_bytes(b"VERSION_A")
  (self.root/"candidate.txt").write_bytes(b"VERSION_B")
 def tearDown(self):self.tmp.cleanup()
 def test_good_policy_and_commit(self):
  self.assertEqual(simulate()[-1],"commit_transaction")
  self.assertEqual(run(self.root),"COMMITTED")
  self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_B")
 def test_health_failure_policy_and_rollback(self):
  self.assertEqual(simulate(fail_at=Stage.HEALTHY)[-1],"launch_restored_version")
  self.assertEqual(run(self.root,health=False),"ROLLED_BACK")
  self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_A")
 def test_interrupted_switch_recovery(self):
  with self.assertRaises(RuntimeError):run(self.root,crash="switched")
  self.assertEqual(run(self.root),"RECOVERED_OLD")
  self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_A")
 def test_unverified_process_blocks_precheck(self):
  from mac_lifecycle_policy import Refused
  with self.assertRaises(Refused):
   plan(Stage.PRECHECK,signed=True,identity_still_matches=False)
  self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_A")
if __name__=="__main__":unittest.main()
