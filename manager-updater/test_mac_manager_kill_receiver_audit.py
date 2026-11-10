import unittest
from mac_manager_kill_receiver_audit import examine
class Tests(unittest.TestCase):
 def test_popen_assigned_receiver(self):
  src="def f():\n p=Popen(['x'])\n p.kill()\n"
  self.assertEqual(examine(src)[0][2],"DIRECT_POPEN_ASSIGN")
 def test_unproven_receiver(self):
  src="def f(p):\n p.kill()\n"
  self.assertEqual(examine(src)[0][2],"UNPROVEN")
 def test_reassigned_receiver(self):
  src="def f():\n p=Popen(['x'])\n p=get_other()\n p.kill()\n"
  self.assertEqual(examine(src)[0][2],"UNPROVEN")
if __name__=="__main__":unittest.main()
