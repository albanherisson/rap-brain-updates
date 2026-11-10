import unittest
from mac_manager_controlflow_locations import summary

class Tests(unittest.TestCase):
    def test_call_locations(self):
        data=b"def f():\n try:\n  os.kill(2,9)\n except OSError:\n  pass\n"
        r=summary(data.decode())
        self.assertEqual(r[0][0],"kill")
        self.assertEqual(r[0][1],3)
        self.assertIn("try",r[0][2])
    def test_does_not_confuse_literals(self):
        self.assertEqual(summary('x="os.kill(1,2)"\n'),[])
    def test_multiple_calls(self):
        self.assertEqual([x[0] for x in summary('server.serve_forever()\nserver.shutdown()\n')],["serve_forever","shutdown"])

if __name__=="__main__": unittest.main()
