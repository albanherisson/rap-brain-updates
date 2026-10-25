"""Validated, read-only evidence for installed Manager's process handling.

Multiple assignments to each kill() receiver mean static provenance is NOT a
complete proof. Never use these observations as permission to stop anything.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class ReceiverObservation:
    line:int
    direct_name:bool
    nearest_assignment_popen:bool
    single_assignment:bool

INSTALLED_SHA="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
CALLS=(ReceiverObservation(439,True,True,False),
       ReceiverObservation(459,True,True,False))

def decision(observations=CALLS):
    if not isinstance(observations,tuple) or len(observations)!=2:
        return "REFUSE_UNVERIFIED"
    if any(type(x) is not ReceiverObservation or not x.direct_name or
           not x.nearest_assignment_popen or not x.single_assignment
           for x in observations):
        return "REFUSE_AMBIGUOUS_PROCESS_PROVENANCE"
    return "STATIC_PROVENANCE_ONLY_NOT_STOP_AUTHORIZATION"
