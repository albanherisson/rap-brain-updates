"""Pure, side-effect-free macOS update lifecycle policy.

This module never starts, stops, or signals any OS process. A future external
supervisor must supply authenticated process identities and perform actions.
"""
from dataclasses import dataclass
from enum import Enum

class Refused(ValueError):
    pass

class Stage(str, Enum):
    PRECHECK = "precheck"
    STOPPED = "stopped"
    SWITCHED = "switched"
    STARTED = "started"
    HEALTHY = "healthy"
    COMMITTED = "committed"
    ROLLBACK = "rollback"
    RESTORED = "restored"
    FAILED = "failed"

@dataclass(frozen=True)
class Identity:
    pid: int
    start_ns: int
    script_sha256: str
    owner_uid: int
    port: int
    verified_local_server: bool

    def __post_init__(self):
        if type(self.pid) is not int or self.pid < 2: raise Refused("PID invalid")
        if type(self.start_ns) is not int or self.start_ns <= 0: raise Refused("Start time invalid")
        if type(self.owner_uid) is not int or self.owner_uid < 0: raise Refused("User invalid")
        if type(self.port) is not int or not 1024 <= self.port <= 65535: raise Refused("Port invalid")
        if type(self.script_sha256) is not str or len(self.script_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.script_sha256):
            raise Refused("Script fingerprint invalid")
        if self.verified_local_server is not True: raise Refused("Server ownership not verified")

@dataclass(frozen=True)
class Action:
    name: str
    stage: Stage

def same_process(before, after):
    return isinstance(before, Identity) and isinstance(after, Identity) and before == after

def plan(stage: Stage, *, identity_still_matches=False, stopped=False, signed=False,
         switched=False, started=False, healthy=False, restored=False):
    if stage == Stage.PRECHECK:
        if signed is not True or identity_still_matches is not True:
            raise Refused("Signed payload and exact process identity required")
        return Action("request_cooperative_stop", Stage.STOPPED)
    if stage == Stage.STOPPED:
        if stopped is not True: raise Refused("Process exit unconfirmed")
        return Action("switch_with_journal", Stage.SWITCHED)
    if stage == Stage.SWITCHED:
        if switched is not True: return Action("restore_backup", Stage.ROLLBACK)
        return Action("launch_new_from_external_worker", Stage.STARTED)
    if stage == Stage.STARTED:
        if started is not True: return Action("restore_backup", Stage.ROLLBACK)
        return Action("probe_authenticated_health", Stage.HEALTHY)
    if stage == Stage.HEALTHY:
        if healthy is not True: return Action("restore_backup", Stage.ROLLBACK)
        return Action("commit_transaction", Stage.COMMITTED)
    if stage == Stage.ROLLBACK:
        if restored is not True: return Action("preserve_backup_and_abort", Stage.FAILED)
        return Action("launch_restored_version", Stage.RESTORED)
    raise Refused("Terminal or unknown stage cannot transition")

def simulate(*, fail_at=None):
    """An abstract plan trace. NO file/system calls."""
    trace=[]
    stage=Stage.PRECHECK
    observed={"identity_still_matches":True,"signed":True,
              "stopped":True,"switched":True,"started":True,
              "healthy":True,"restored":True}
    for _ in range(8):
        if fail_at == stage:
            if stage == Stage.PRECHECK:observed["identity_still_matches"]=False
            if stage == Stage.STOPPED:observed["stopped"]=False
            if stage == Stage.SWITCHED:observed["switched"]=False
            if stage == Stage.STARTED:observed["started"]=False
            if stage == Stage.HEALTHY:observed["healthy"]=False
            if stage == Stage.ROLLBACK:observed["restored"]=False
        action=plan(stage,**observed)
        trace.append(action.name)
        if action.stage in (Stage.COMMITTED,Stage.RESTORED,Stage.FAILED):
            return trace
        stage=action.stage
    raise Refused("Policy did not terminate")
