import tempfile,unittest
from pathlib import Path
from fixture_confined_transaction import MARKER,replace_fixture
from manager_path_confinement import PathEscape
class Tests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
  self.root=Path(t.name)/"DisposableManagerDataFixture";self.root.mkdir()
  (self.root/".fixture-marker").write_bytes(MARKER)
  (self.root/"manager.py").write_bytes(b"old")
 def test_commit(self):
  self.assertEqual(replace_fixture(self.root,"manager.py",b"new",health=True),"COMMITTED_FIXTURE")
  self.assertEqual((self.root/"manager.py").read_bytes(),b"new")
 def test_rollback(self):
  self.assertEqual(replace_fixture(self.root,"manager.py",b"new",health=False),"ROLLED_BACK")
  self.assertEqual((self.root/"manager.py").read_bytes(),b"old")
 def test_escape_refused(self):
  with self.assertRaises(PathEscape):replace_fixture(self.root,"../manager.py",b"new",health=True)
 def test_symlink_refused(self):
  (self.root/"escape").symlink_to("/tmp")
  with self.assertRaises(PathEscape):replace_fixture(self.root,"escape/outside",b"new",health=True)
 def test_unmarked_refused(self):
  (self.root/".fixture-marker").unlink()
  with self.assertRaises((OSError,PathEscape)):replace_fixture(self.root,"manager.py",b"new",health=True)
if __name__=="__main__":unittest.main()
