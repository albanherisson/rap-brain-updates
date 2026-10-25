"""Fixture-only integrated supervisor orchestration.

All process lifecycle behavior is simulated; no installed app or PID is touched.
This is an integration test seam, NOT an installer or production supervisor.
"""
from dataclasses import dataclass
from pathlib import Path
from disposable_cooperative_supervisor import DummyServer, fixture_transaction, Rejected
from disposable_bundle_transaction import drill, inventory

@dataclass(frozen=True)
class Result:
    transaction: str
    bundle: str
    restored: bool

def execute(transaction_root, bundle_root, server, secret, *, signed=True, health=True):
    transaction_root=Path(transaction_root)
    bundle_root=Path(bundle_root)
    before=inventory(bundle_root)
    # Validate both targets BEFORE cooperative shutdown of the fixture.
    if transaction_root.name!="DisposableSupervisorFixture":
        raise Rejected("not disposable transaction")
    if not isinstance(server,DummyServer) or signed is not True:
        raise Rejected("fixture server / signed release required")
    if "Contents/Resources/manager.py" not in before or "Contents/Info.plist" not in before:
        raise Rejected("incomplete bundle")
    # Bundle change deliberately occurs after dummy stop; both stages are fixture-only.
    txn=fixture_transaction(transaction_root,server,secret,signed=signed,health=health)
    bundle=drill(bundle_root,signed_verified=signed,healthy=health)
    restored=inventory(bundle_root)==before
    if health is False and not restored:
        raise Rejected("bundle rollback differs")
    return Result(txn,bundle,restored)
