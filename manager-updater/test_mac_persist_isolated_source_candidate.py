import hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import mac_persist_isolated_source_candidate as module
class Tests(unittest.TestCase):
 def test_reject_unpinned(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(ValueError):module.write_candidate(b"not source",Path(t)/"candidate.DISABLED")
 def test_refuse_existing(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/"candidate.DISABLED";p.write_bytes(b"original")
   with self.assertRaises(ValueError):module.write_candidate(b"anything",p)
   self.assertEqual(p.read_bytes(),b"original")
if __name__=="__main__":unittest.main()
