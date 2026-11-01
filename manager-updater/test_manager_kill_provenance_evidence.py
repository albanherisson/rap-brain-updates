import unittest
from manager_kill_provenance_evidence import ReceiverObservation,CALLS,decision
class Tests(unittest.TestCase):
 def test_real_manager_remains_blocked(self):
  self.assertEqual(decision(),"REFUSE_AMBIGUOUS_PROCESS_PROVENANCE")
 def test_incomplete_evidence_refused(self):
  self.assertEqual(decision(()),"REFUSE_UNVERIFIED")
 def test_single_assignment_still_not_authorization(self):
  observations=tuple(ReceiverObservation(x.line,True,True,True) for x in CALLS)
  self.assertEqual(decision(observations),"STATIC_PROVENANCE_ONLY_NOT_STOP_AUTHORIZATION")
if __name__=="__main__":unittest.main()
