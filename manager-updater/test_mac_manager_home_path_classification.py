import unittest
from mac_manager_home_path_classification import audit
class Tests(unittest.TestCase):
 def test_simple(self):
  counts=audit(b"from pathlib import Path\nx=Path.home()/'folder'\ny=Path.home()/other\n")
  self.assertEqual(counts["home_calls"],2)
  self.assertEqual(counts["literal_home_children"],1)
  self.assertEqual(counts["computed_home_paths"],1)
if __name__=="__main__":unittest.main()
