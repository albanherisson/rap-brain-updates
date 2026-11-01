import unittest
from mac_candidate_static_gate import inspect_candidate,gate
class Tests(unittest.TestCase):
 def test_suspicious_calls_identified(self):
  d=b"_rb_disabled_popen([])\n_rb_isolated_home()\nPath.home()\nPopen([])\nopen('file')\n"
  c=inspect_candidate(d)
  self.assertEqual((c["blocked_popen"],c["isolated_home"],c["unblocked_popen"],c["native_home"],c["remaining_file_ops"]),(1,1,1,1,1))
 def test_unknown_hash_rejected(self):
  with self.assertRaises(ValueError):gate(b"pass")
if __name__=="__main__":unittest.main()
