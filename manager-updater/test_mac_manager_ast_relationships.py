import unittest
from mac_manager_ast_relationships import report
class Tests(unittest.TestCase):
 def test_kill_and_siblings(self):
  s="def f():\n p=Popen(['python'])\n p.kill()\n p.wait()\n"
  r=report(s)
  self.assertEqual(r[0][0],"kill")
  self.assertEqual(r[0][2],"Name")
  self.assertTrue(r[0][4])
  self.assertTrue(r[0][5])
 def test_literals_never_count(self):
  self.assertEqual(report('text="p.kill()"\n'),[])
 def test_server(self):
  s="def start():\n server=mod.ThreadingHTTPServer((0,0),None)\n server.serve_forever()\n"
  r=report(s)
  self.assertEqual([x[0] for x in r],["ThreadingHTTPServer","serve_forever"])
if __name__=="__main__":unittest.main()
