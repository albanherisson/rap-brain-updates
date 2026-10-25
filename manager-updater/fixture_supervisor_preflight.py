"""Single-use signed/identity preflight for disposable supervisor transaction.

Simulated signature flag is NOT cryptographic verification. No real app accepted.
"""
from dataclasses import dataclass
from fixture_confined_transaction import replace_fixture

@dataclass(frozen=True)
class FixtureApproval:
    candidate_digest:str
    authenticated_shutdown:bool
    signed_catalog_verified:bool
    process_identity_verified:bool

def run_preflighted_fixture(root,data,approval,*,healthy):
    import hashlib
    if not isinstance(approval,FixtureApproval):
        raise ValueError("missing approval")
    if approval.candidate_digest!=hashlib.sha256(data).hexdigest():
        raise ValueError("candidate digest mismatch")
    if not all((approval.authenticated_shutdown,approval.signed_catalog_verified,approval.process_identity_verified)):
        raise ValueError("preflight missing")
    return replace_fixture(root,"manager.py",data,health=healthy)
