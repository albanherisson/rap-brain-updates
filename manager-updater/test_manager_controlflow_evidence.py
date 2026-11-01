import unittest
from manager_controlflow_evidence import lifecycle_review,OBSERVED,EXPECTED_SHA
class Tests(unittest.TestCase):
    def test_verified_observation(self):
        self.assertEqual(len(EXPECTED_SHA),64)
        self.assertEqual([x.line for x in OBSERVED if x.name=="kill"],[439,459])
    def test_no_stop_authorization(self):
        result=lifecycle_review()
        self.assertIs(result["supervisor_stop_allowed"],False)
        self.assertIs(result["installation_allowed"],False)
    def test_unknown_kill_semantics(self):
        self.assertEqual(lifecycle_review()["existing_kill_semantics"],"UNKNOWN_DO_NOT_REUSE")
if __name__=="__main__":unittest.main()
