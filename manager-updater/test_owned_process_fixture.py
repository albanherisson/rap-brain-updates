import tempfile,time,unittest
from pathlib import Path
from owned_process_fixture import MARKER,prepare_fixture,start_owned,stop_owned,read_ready,Refuse,owned_is_running
CODE='import time\nprint("DISPOSABLE_READY",flush=True)\nwhile True:time.sleep(.1)\n'
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.root=Path(self.tmp.name)/"DisposableProcessFixture"
  self.root.mkdir()
  (self.root/"fixture.marker").write_bytes(MARKER)
  self.script=self.root/"fixture_child.py"
  self.script.write_text(CODE)
  self.child=None
 def tearDown(self):
  if self.child is not None and self.child.process.poll() is None:
   self.child.process.kill();self.child.process.wait(timeout=3)
  self.tmp.cleanup()
 def test_start_and_owned_stop(self):
  self.child=start_owned(self.root)
  self.assertTrue(read_ready(self.child))
  self.assertEqual(stop_owned(self.child),"STOPPED_OWN_CHILD")
 def test_restart_with_new_handle(self):
  self.child=start_owned(self.root);self.assertTrue(read_ready(self.child))
  stop_owned(self.child)
  old=self.child.process.pid
  self.child=start_owned(self.root)
  self.assertTrue(read_ready(self.child))
  self.assertNotEqual(old,self.child.process.pid)
 def test_script_mutation_blocks_stop(self):
  self.child=start_owned(self.root);self.assertTrue(read_ready(self.child))
  self.script.write_text(CODE+"# modified")
  with self.assertRaises(Refuse):stop_owned(self.child)
 def test_unmarked_root_refused(self):
  (self.root/"fixture.marker").unlink()
  with self.assertRaises(Exception):start_owned(self.root)
 def test_real_app_name_refused(self):
  wrong=self.root.parent/"Rap Brain Manager.app"
  self.root.rename(wrong)
  with self.assertRaises(Refuse):start_owned(wrong)
 def test_no_arbitrary_pid(self):
  with self.assertRaises(Refuse):owned_is_running(12345)
 def test_already_exited(self):
  self.child=start_owned(self.root);self.assertTrue(read_ready(self.child))
  self.child.process.terminate();self.child.process.wait(timeout=3)
  self.assertEqual(stop_owned(self.child),"ALREADY_EXITED")
 def test_invalid_timeout(self):
  self.child=start_owned(self.root);self.assertTrue(read_ready(self.child))
  with self.assertRaises(Refuse):stop_owned(self.child,0)
if __name__=="__main__":unittest.main()
