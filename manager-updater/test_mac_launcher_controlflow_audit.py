import unittest
from mac_launcher_controlflow_audit import analyze
class Tests(unittest.TestCase):
 def test_classifies(self):
  r=analyze('import subprocess\ndef start():\n subprocess.Popen(["x"])\n')
  self.assertEqual(len(r["Popen"]),1)
  self.assertEqual(r["Popen"][0][0],"function")
 def test_no_code_execution(self):
  r=analyze('raise Exception("DO_NOT_EXECUTE")\n')
  self.assertEqual(sum(len(x) for x in r.values()),0)
 def test_kill_in_condition(self):
  r=analyze('if True:\n import os\n os.kill(12,15)\n')
  self.assertEqual(r["kill"][0][0],"conditional")
if __name__=="__main__":unittest.main()
