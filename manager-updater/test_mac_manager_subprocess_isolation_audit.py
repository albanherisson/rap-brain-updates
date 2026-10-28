import unittest
from mac_manager_subprocess_isolation_audit import classify
class Tests(unittest.TestCase):
 def test_keywords(self):
  s=b"Popen(['a'],env={},cwd='/tmp',shell=True)\n"
  x=classify(s)
  self.assertEqual((x["popen_total"],x["explicit_env_keyword"],x["explicit_cwd_keyword"],x["shell_true_literal"]),(1,1,1,1))
 def test_literals_not_calls(self):
  self.assertEqual(classify(b'x="Popen()"\n')["popen_total"],0)
if __name__=="__main__":unittest.main()
