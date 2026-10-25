import ast,unittest
from mac_launcher_behavior_audit import report_from_source
class Tests(unittest.TestCase):
 def test_summarizes_without_constants(self):
  summary=report_from_source('import subprocess\nsecret="PRIVATE"\nsubprocess.Popen(["demo"])\n')
  self.assertEqual(summary["popen"],1)
  self.assertNotIn("PRIVATE",str(summary))
 def test_detects_kill(self):
  result=report_from_source('import os\nos.kill(123,15)')
  self.assertEqual(result["signals_kill"],1)
 def test_no_side_effects_from_parsing(self):
  output=report_from_source('raise RuntimeError("should not execute")')
  self.assertEqual(output["popen"],0)
if __name__=="__main__":unittest.main()
