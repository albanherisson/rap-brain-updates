import unittest
from mac_manager_path_provenance import summarize
class Tests(unittest.TestCase):
 def test_home_and_absolute(self):
  rows=summarize(b"from pathlib import Path\na=Path.home()/'App'\na.mkdir()\nopen('/tmp/test','w')\n")
  self.assertTrue(any(r[1]=="mkdir" and "joined_home_call" in r[2] for r in rows))
  self.assertTrue(any(r[1]=="open" and r[2]=="absolute_literal" for r in rows))
 def test_unresolved_fails_open_never(self):
  rows=summarize(b"import subprocess\nsubprocess.Popen(argv)\n")
  self.assertTrue(any(r[1]=="Popen" and r[2]=="variable_unresolved" for r in rows))
if __name__=="__main__":unittest.main()
