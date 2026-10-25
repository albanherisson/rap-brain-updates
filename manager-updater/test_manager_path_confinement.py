import os,tempfile,unittest
from pathlib import Path
from manager_path_confinement import confined_path,sanitized_environment,PathEscape
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)
 def test_regular_nested_path(self):
  self.assertEqual(confined_path(self.root,"storage/metadata.json"),self.root/"storage/metadata.json")
 def test_parent_escape(self):
  for p in ("../secret","safe/../../etc","/etc/passwd"):
   with self.subTest(p=p),self.assertRaises(PathEscape):confined_path(self.root,p)
 def test_internal_symlink_escape(self):
  (self.root/"link").symlink_to("/tmp")
  with self.assertRaises(PathEscape):confined_path(self.root,"link/secret")
 def test_environment_does_not_inherit_secrets(self):
  env=sanitized_environment(self.root,{"SECRET_TOKEN":"leak"})
  self.assertNotIn("SECRET_TOKEN",env)
  self.assertEqual(env["HOME"],str(self.root.resolve()))
 def test_reject_symlink_root(self):
  link=self.root.parent/(self.root.name+"-link")
  link.symlink_to(self.root)
  self.addCleanup(link.unlink)
  with self.assertRaises(PathEscape):confined_path(link,"file")
if __name__=="__main__":unittest.main()
