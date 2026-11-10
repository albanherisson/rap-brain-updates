import unittest
from dataclasses import replace
from manager_isolation_release_gate import OBSERVED,remaining_blockers,permitted_to_execute_installed_manager_copy
class Tests(unittest.TestCase):
 def test_observed_copy_denied(self):
  self.assertFalse(permitted_to_execute_installed_manager_copy(OBSERVED))
  self.assertEqual(OBSERVED.popen_lines_without_explicit_env_cwd,(399,467,837))
 def test_even_fully_checked_requires_independent_approval(self):
  hypothetical=replace(OBSERVED,data_root_configurable=True,children_inherit_explicit_sandbox=True,filesystem_targets_verified=True,authenticated_stop_integrated=True,restart_probe_integrated=True)
  self.assertEqual(remaining_blockers(hypothetical),())
  self.assertFalse(permitted_to_execute_installed_manager_copy(hypothetical))
 def test_real_blockers(self):
  self.assertEqual(len(remaining_blockers(OBSERVED)),5)
if __name__=="__main__":unittest.main()
