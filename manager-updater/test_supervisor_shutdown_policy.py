import unittest
from supervisor_shutdown_policy import Capabilities,ShutdownRefused,decide,observed_manager
class Tests(unittest.TestCase):
    def test_installed_manager_refused(self):
        with self.assertRaises(ShutdownRefused): decide(observed_manager())
    def test_no_authentication(self):
        c=Capabilities(True,1,1,0,2,0,False,True)
        with self.assertRaises(ShutdownRefused):decide(c)
    def test_no_supervisor(self):
        c=Capabilities(True,1,1,1,0,0,True,False)
        with self.assertRaises(ShutdownRefused):decide(c)
    def test_known_cooperative_endpoint_is_planning_only(self):
        c=Capabilities(True,1,1,1,0,0,True,True)
        self.assertEqual(decide(c),"COOPERATIVE_ENDPOINT_ONLY_NO_PID_SIGNAL")
    def test_unverified_source(self):
        c=Capabilities(False,1,1,1,0,0,True,True)
        with self.assertRaises(ShutdownRefused):decide(c)
    def test_unknown_server(self):
        c=Capabilities(True,0,1,1,0,0,True,True)
        with self.assertRaises(ShutdownRefused):decide(c)
if __name__=="__main__":unittest.main()
