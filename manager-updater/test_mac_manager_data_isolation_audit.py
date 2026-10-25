import unittest
from mac_manager_data_isolation_audit import inspect
class Tests(unittest.TestCase):
 def test_counts(self):
  x=inspect(b"from pathlib import Path\na=Path.home()\na.mkdir()\na.write_text('x')\n")
  self.assertEqual((x["home"],x["mkdir"],x["write_text"]),(1,1,1))
 def test_strings_not_executed(self):
  self.assertFalse(any(inspect(b'x="open() write_text()"\n').values()))
if __name__=="__main__":unittest.main()
