import tempfile
import unittest
from pathlib import Path
from disposable_bundle_transaction import drill,inventory,BundleRefused

class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)/"DisposableBundleFixture.app"
  (self.root/"Contents/Resources").mkdir(parents=True)
  (self.root/"Contents/Info.plist").write_bytes(b"ICON_AND_METADATA")
  (self.root/"Contents/Resources/manager.py").write_bytes(b"print('v1')\n")
  (self.root/"Contents/Resources/custom-icon.icns").write_bytes(b"ICON")
  self.original=inventory(self.root)
 def test_healthy_commit_preserves_other_files(self):
  self.assertEqual(drill(self.root,signed_verified=True,healthy=True),"COMMITTED_FIXTURE")
  changed=inventory(self.root)
  self.assertNotEqual(changed["Contents/Resources/manager.py"],self.original["Contents/Resources/manager.py"])
  for key in self.original:
   if key!="Contents/Resources/manager.py":self.assertEqual(changed[key],self.original[key])
 def test_failed_health_restores_every_byte(self):
  self.assertEqual(drill(self.root,signed_verified=True,healthy=False),"ROLLED_BACK")
  self.assertEqual(inventory(self.root),self.original)
 def test_unsigned_refused(self):
  with self.assertRaises(BundleRefused):drill(self.root,signed_verified=False,healthy=True)
  self.assertEqual(inventory(self.root),self.original)
 def test_real_app_name_refused(self):
  with self.assertRaises(BundleRefused):drill(self.root.parent,signed_verified=True,healthy=True)
 def test_symlink_refused(self):
  (self.root/"Contents/Resources/alias").symlink_to("manager.py")
  with self.assertRaises(BundleRefused):inventory(self.root)
if __name__=="__main__":unittest.main()
