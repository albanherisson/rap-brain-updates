import unittest
from mac_manager_capability_inventory import inventory

class Tests(unittest.TestCase):
    def test_detect_shutdown(self):
        funcs, counts=inventory(b"class A:\n def stop(self):\n  self.shutdown()\n")
        self.assertEqual(funcs,1)
        self.assertEqual(counts.get("shutdown"),1)
    def test_ignores_strings_and_comments(self):
        _,counts=inventory(b'x="kill() shutdown()" # terminate()\n')
        self.assertEqual(counts,{})
    def test_no_source_execution(self):
        _,counts=inventory(b"import os\nos.remove('/tmp/should-not-execute')\n")
        self.assertEqual(counts,{})
if __name__=="__main__":unittest.main()
