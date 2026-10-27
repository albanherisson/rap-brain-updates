import os,tempfile,unittest
from pathlib import Path
from mac_disposable_process_controller import OwnedProcess
from mac_lifecycle_policy import Refused

WORKER='import time\ntime.sleep(30)\n'
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.root=Path(self.tmp.name)
  self.marker=self.root/"fixture.marker"
  self.marker.write_bytes(b"RAPBRAIN_DISPOSABLE_PROCESS_V1\n")
  self.script=self.root/"worker.py"
  self.script.write_text(WORKER)
  self.ctrl=OwnedProcess(marker=self.marker,script=self.script,timeout=1.5)
 def tearDown(self):
  self.ctrl.stop()
  self.tmp.cleanup()
 def test_launch_stop(self):
  proc=self.ctrl.launch(healthy=lambda p:p.poll() is None)
  self.assertIsNone(proc.poll())
  self.assertTrue(self.ctrl.stop())
  self.assertIsNotNone(proc.poll())
 def test_restart(self):
  first=self.ctrl.launch(healthy=lambda p:True)
  second=self.ctrl.restart(healthy=lambda p:True)
  self.assertNotEqual(first.pid,second.pid)
  self.assertIsNotNone(first.poll())
 def test_failed_health_stops_owned(self):
  with self.assertRaises(Refused):self.ctrl.launch(healthy=lambda p:False)
  self.assertIsNone(self.ctrl._proc)
 def test_bad_marker(self):
  self.marker.write_bytes(b"WRONG")
  with self.assertRaises(Refused):self.ctrl.launch(healthy=lambda p:True)
 def test_no_health_callback(self):
  with self.assertRaises(Refused):self.ctrl.launch(healthy=None)
 def test_reject_other_script(self):
  self.ctrl.script=self.root/"manager.py"
  self.ctrl.script.write_text(WORKER)
  with self.assertRaises(Refused):self.ctrl.launch(healthy=lambda p:True)
 def test_no_unowned_restart(self):
  with self.assertRaises(Refused):self.ctrl.restart(healthy=lambda p:True)
 def test_no_unowned_stop(self):self.assertFalse(self.ctrl.stop())
 def test_reject_symlink_script(self):
  target=self.root/"target.py";target.write_text(WORKER)
  self.script.unlink();self.script.symlink_to(target)
  with self.assertRaises(Refused):self.ctrl.launch(healthy=lambda p:True)
 def test_double_launch_refused(self):
  self.ctrl.launch(healthy=lambda p:True)
  with self.assertRaises(Refused):self.ctrl.launch(healthy=lambda p:True)
if __name__=="__main__":unittest.main()
