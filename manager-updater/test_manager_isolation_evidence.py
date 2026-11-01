import unittest
from manager_isolation_evidence import EVIDENCE,isolation_gate,IsolationEvidence
class Tests(unittest.TestCase):
 def test_installed_manager_blocked(self):
  self.assertEqual(isolation_gate(EVIDENCE),"BLOCK_EXECUTABLE_COPY_UNTIL_FULL_PATH_REVIEW")
 def test_no_bypass_from_absence_of_shell(self):
  self.assertEqual(EVIDENCE.shell_true,0)
  self.assertNotEqual(isolation_gate(EVIDENCE),"SAFE_TO_LAUNCH")
 def test_even_ideal_counts_require_sandbox(self):
  e=IsolationEvidence(absolute_literals=0,popen_count=2,explicit_env=2)
  self.assertEqual(isolation_gate(e),"REQUIRES_INDEPENDENT_SANDBOX_VALIDATION")
if __name__=="__main__":unittest.main()
