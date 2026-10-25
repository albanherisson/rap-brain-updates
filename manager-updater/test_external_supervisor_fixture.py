import contextlib,fcntl,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from external_supervisor_fixture import run,MARKER
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.root=Path(self.temp.name)/"DisposableSupervisorFixture"
  self.root.mkdir()
  for name,content in (("fixture.marker",MARKER),("manager.txt",b"old"),("candidate.txt",b"new")):
   (self.root/name).write_bytes(content)
 def tearDown(self):self.temp.cleanup()
 def test_commit(self):self.assertEqual(run(self.root),"COMMITTED")
 def test_rollback(self):
  self.assertEqual(run(self.root,False),"ROLLED_BACK")
  self.assertEqual((self.root/"manager.txt").read_bytes(),b"old")
 def test_recovery_prepared(self):
  with self.assertRaises(RuntimeError):run(self.root,crash="prepared")
  self.assertEqual(run(self.root),"RECOVERED_OLD")
 def test_recovery_switched(self):
  with self.assertRaises(RuntimeError):run(self.root,crash="switched")
  self.assertEqual(run(self.root),"RECOVERED_OLD")
  self.assertEqual((self.root/"manager.txt").read_bytes(),b"old")
 def test_real_app_refused(self):
  self.root.rename(self.root.parent/"Rap Brain Manager.app")
  with self.assertRaises(ValueError):run(self.root.parent/"Rap Brain Manager.app")
 def test_bad_marker(self):
  (self.root/"fixture.marker").write_bytes(b"wrong")
  with self.assertRaises(ValueError):run(self.root)
 def test_symlink_backup(self):
  (self.root/"backup.txt").symlink_to("/tmp/x")
  with self.assertRaises(ValueError):run(self.root)
 def test_backup_damage(self):
  with self.assertRaises(RuntimeError):run(self.root,crash="switched")
  (self.root/"backup.txt").write_bytes(b"damage")
  with self.assertRaises(ValueError):run(self.root)
 def test_replay(self):
  self.assertEqual(run(self.root),"COMMITTED")
  self.assertEqual(run(self.root),"COMMITTED")
 def test_lock(self):
  fd=os.open(self.root/"transaction.lock",os.O_CREAT|os.O_RDWR,0o600)
  try:
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   p=subprocess.run([sys.executable,"-c","import sys;from external_supervisor_fixture import run;run(sys.argv[1])",str(self.root)],cwd=str(Path(__file__).parent),capture_output=True)
   self.assertNotEqual(p.returncode,0)
  finally:os.close(fd)
if __name__=="__main__":unittest.main()
