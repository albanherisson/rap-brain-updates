"""Disposable process restart combined with a versioned fixture; NO installed app."""
import tempfile,unittest
from pathlib import Path
from owned_process_fixture import MARKER,start_owned,stop_owned,Refuse

CHILD='''from pathlib import Path
import time
version=Path("version.txt").read_text().strip()
print("DISPOSABLE_READY" if version in ("A","B") else "BAD",flush=True)
while True:time.sleep(.1)
'''
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.root=Path(self.temp.name)/"DisposableProcessFixture"
  self.root.mkdir()
  (self.root/"fixture.marker").write_bytes(MARKER)
  (self.root/"fixture_child.py").write_text(CHILD)
  self.version=self.root/"version.txt"
  self.version.write_text("A")
  self.child=None
 def tearDown(self):
  if self.child and self.child.process.poll() is None:
   self.child.process.kill();self.child.process.wait(timeout=3)
  self.temp.cleanup()
 def test_change_and_restart(self):
  self.child=start_owned(self.root)
  self.assertEqual(self.child.process.stdout.readline().strip(),"DISPOSABLE_READY")
  self.assertEqual(stop_owned(self.child),"STOPPED_OWN_CHILD")
  self.version.write_text("B")
  self.child=start_owned(self.root)
  self.assertEqual(self.child.process.stdout.readline().strip(),"DISPOSABLE_READY")
  self.assertEqual(stop_owned(self.child),"STOPPED_OWN_CHILD")
  self.assertEqual(self.version.read_text(),"B")
 def test_rollback_after_failed_health(self):
  self.child=start_owned(self.root)
  self.assertEqual(self.child.process.stdout.readline().strip(),"DISPOSABLE_READY")
  stop_owned(self.child)
  self.version.write_text("BROKEN")
  self.child=start_owned(self.root)
  self.assertEqual(self.child.process.stdout.readline().strip(),"BAD")
  stop_owned(self.child)
  self.version.write_text("A")
  self.child=start_owned(self.root)
  self.assertEqual(self.child.process.stdout.readline().strip(),"DISPOSABLE_READY")
  stop_owned(self.child)
  self.assertEqual(self.version.read_text(),"A")
if __name__=="__main__":unittest.main()
