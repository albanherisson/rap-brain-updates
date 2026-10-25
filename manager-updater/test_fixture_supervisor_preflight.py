import hashlib,tempfile,unittest
from pathlib import Path
from fixture_confined_transaction import MARKER
from fixture_supervisor_preflight import FixtureApproval,run_preflighted_fixture
class Tests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.root=Path(tmp.name)/"DisposableManagerDataFixture";self.root.mkdir()
  (self.root/".fixture-marker").write_bytes(MARKER)
  (self.root/"manager.py").write_bytes(b"old")
 def approval(self,**changes):
  d=dict(candidate_digest=hashlib.sha256(b"new").hexdigest(),authenticated_shutdown=True,signed_catalog_verified=True,process_identity_verified=True)
  d.update(changes)
  return FixtureApproval(**d)
 def test_commit(self):
  self.assertEqual(run_preflighted_fixture(self.root,b"new",self.approval(),healthy=True),"COMMITTED_FIXTURE")
 def test_rollback(self):
  self.assertEqual(run_preflighted_fixture(self.root,b"new",self.approval(),healthy=False),"ROLLED_BACK")
  self.assertEqual((self.root/"manager.py").read_bytes(),b"old")
 def test_missing_identity_refuses_without_mutation(self):
  with self.assertRaises(ValueError):run_preflighted_fixture(self.root,b"new",self.approval(process_identity_verified=False),healthy=True)
  self.assertEqual((self.root/"manager.py").read_bytes(),b"old")
 def test_digest_mismatch(self):
  with self.assertRaises(ValueError):run_preflighted_fixture(self.root,b"tampered",self.approval(),healthy=True)
  self.assertEqual((self.root/"manager.py").read_bytes(),b"old")
if __name__=="__main__":unittest.main()
