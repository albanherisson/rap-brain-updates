import tempfile
import unittest
from pathlib import Path
from disposable_cooperative_supervisor import DummyServer,Rejected
from disposable_bundle_transaction import inventory
from fixture_only_supervisor_orchestration import execute
from external_supervisor_fixture import MARKER
SECRET=b"fixture-test-secret-that-is-not-a-production-key"

class Tests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
  base=Path(t.name)
  self.txn=base/"DisposableSupervisorFixture";self.txn.mkdir()
  (self.txn/"fixture.marker").write_bytes(MARKER)
  (self.txn/"manager.txt").write_bytes(b"VERSION_A")
  (self.txn/"candidate.txt").write_bytes(b"VERSION_B")
  self.bundle=base/"DisposableBundleFixture.app"
  (self.bundle/"Contents/Resources").mkdir(parents=True)
  (self.bundle/"Contents/Info.plist").write_bytes(b"metadata")
  (self.bundle/"Contents/Resources/manager.py").write_bytes(b"old")
  (self.bundle/"Contents/Resources/icon.icns").write_bytes(b"icon")
  self.before=inventory(self.bundle)
 def test_commit(self):
  result=execute(self.txn,self.bundle,DummyServer(SECRET),SECRET)
  self.assertEqual((result.transaction,result.bundle),("COMMITTED","COMMITTED_FIXTURE"))
  self.assertFalse(result.restored)
  self.assertEqual((self.bundle/"Contents/Resources/icon.icns").read_bytes(),b"icon")
 def test_failed_health_rolls_back(self):
  result=execute(self.txn,self.bundle,DummyServer(SECRET),SECRET,health=False)
  self.assertEqual((result.transaction,result.bundle),("ROLLED_BACK","ROLLED_BACK"))
  self.assertTrue(result.restored)
 def test_wrong_secret_refused_before_mutation(self):
  with self.assertRaises(Rejected):
   execute(self.txn,self.bundle,DummyServer(SECRET),b"x"*32)
  self.assertEqual(inventory(self.bundle),self.before)
 def test_unsigned_refused_before_mutation(self):
  with self.assertRaises(Rejected):
   execute(self.txn,self.bundle,DummyServer(SECRET),SECRET,signed=False)
  self.assertEqual(inventory(self.bundle),self.before)
if __name__=="__main__":unittest.main()
