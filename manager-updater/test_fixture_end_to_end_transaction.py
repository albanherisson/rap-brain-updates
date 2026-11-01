import secrets,tempfile,unittest
from pathlib import Path
from fixture_confined_transaction import MARKER
from fixture_end_to_end_transaction import update_fixture
class Tests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.root=Path(tmp.name)/"DisposableManagerDataFixture";self.root.mkdir()
  (self.root/".fixture-marker").write_bytes(MARKER)
  (self.root/"manager.py").write_bytes(b"old")
  self.key=secrets.token_bytes(32)
 def test_authenticated_http_commit(self):
  self.assertEqual(update_fixture(self.root,b"new",self.key,health=True),"COMMITTED_FIXTURE")
  self.assertEqual((self.root/"manager.py").read_bytes(),b"new")
 def test_authenticated_http_rollback(self):
  self.assertEqual(update_fixture(self.root,b"new",self.key,health=False),"ROLLED_BACK")
  self.assertEqual((self.root/"manager.py").read_bytes(),b"old")
 def test_unsigned_refuses_before_stop_and_file_change(self):
  with self.assertRaises(ValueError):update_fixture(self.root,b"new",self.key,health=True,signed=False)
  self.assertEqual((self.root/"manager.py").read_bytes(),b"old")
 def test_unknown_identity_refuses_without_file_change(self):
  with self.assertRaises(ValueError):update_fixture(self.root,b"new",self.key,health=True,identity=False)
  self.assertEqual((self.root/"manager.py").read_bytes(),b"old")
if __name__=="__main__":unittest.main()
