import unittest
from mac_lifecycle_policy import Identity,Stage,Refused,plan,same_process,simulate

SHA="a"*64
def identity(**kw):
 values=dict(pid=48297,start_ns=123456789,script_sha256=SHA,owner_uid=501,port=62788,verified_local_server=True)
 values.update(kw)
 return Identity(**values)

class Tests(unittest.TestCase):
 def test_identity(self):self.assertTrue(same_process(identity(),identity()))
 def test_pid_reuse(self):self.assertFalse(same_process(identity(),identity(start_ns=123456790)))
 def test_different_uid(self):self.assertFalse(same_process(identity(),identity(owner_uid=502)))
 def test_wrong_script(self):self.assertFalse(same_process(identity(),identity(script_sha256="b"*64)))
 def test_different_port(self):self.assertFalse(same_process(identity(),identity(port=62789)))
 def test_unverified_server(self):
  with self.assertRaises(Refused):identity(verified_local_server=False)
 def test_bool_pid(self):
  with self.assertRaises(Refused):identity(pid=True)
 def test_missing_start(self):
  with self.assertRaises(Refused):identity(start_ns=0)
 def test_invalid_hash(self):
  with self.assertRaises(Refused):identity(script_sha256="wrong")
 def test_unsigned(self):
  with self.assertRaises(Refused):plan(Stage.PRECHECK,identity_still_matches=True,signed=False)
 def test_wrong_process(self):
  with self.assertRaises(Refused):plan(Stage.PRECHECK,identity_still_matches=False,signed=True)
 def test_no_exit(self):
  with self.assertRaises(Refused):plan(Stage.STOPPED,stopped=False)
 def test_healthy(self):self.assertEqual(simulate()[-1],"commit_transaction")
 def test_failed_switch(self):self.assertEqual(simulate(fail_at=Stage.SWITCHED)[-1],"launch_restored_version")
 def test_failed_start(self):self.assertEqual(simulate(fail_at=Stage.STARTED)[-1],"launch_restored_version")
 def test_failed_probe(self):self.assertEqual(simulate(fail_at=Stage.HEALTHY)[-1],"launch_restored_version")
 def test_failed_restore(self):self.assertEqual(simulate(fail_at=Stage.ROLLBACK)[-1],"preserve_backup_and_abort") if False else self.assertEqual(plan(Stage.ROLLBACK,restored=False).name,"preserve_backup_and_abort")
 def test_terminal_stage(self):
  with self.assertRaises(Refused):plan(Stage.COMMITTED)
if __name__=="__main__":unittest.main()
