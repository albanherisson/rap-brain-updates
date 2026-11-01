"""Pure process identity policy for a future external supervisor.

Never signals, launches, kills or installs. Inputs are observations acquired
by a separate trusted macOS-specific implementation. Positive results are
NOT authorization to signal a PID: PID reuse can happen after observation.
"""
from dataclasses import dataclass
import hmac
import re

_HEX = re.compile(r"[0-9a-f]{64}\Z")
class IdentityRefused(ValueError):
    pass

@dataclass(frozen=True)
class ProcessObservation:
    pid: int
    uid: int
    start_ns: int
    executable_path: str
    executable_sha256: str
    script_path: str
    script_sha256: str
    loopback_port: int
    port_owner_pid: int
    authenticated_health: bool

    def __post_init__(self):
        if type(self.pid) is not int or not (2 <= self.pid <= 4194304):
            raise IdentityRefused("invalid pid")
        if type(self.uid) is not int or self.uid < 0:
            raise IdentityRefused("invalid user")
        if type(self.start_ns) is not int or self.start_ns <= 0:
            raise IdentityRefused("invalid process birth time")
        if type(self.loopback_port) is not int or not (1024 <= self.loopback_port <= 65535):
            raise IdentityRefused("invalid port")
        if type(self.port_owner_pid) is not int or self.port_owner_pid != self.pid:
            raise IdentityRefused("socket does not belong to process")
        if self.authenticated_health is not True:
            raise IdentityRefused("health authentication missing")
        for path in (self.executable_path, self.script_path):
            if type(path) is not str or not path.startswith("/") or "\\x00" in path or "\\n" in path:
                raise IdentityRefused("invalid absolute path")
        for sha in (self.executable_sha256, self.script_sha256):
            if type(sha) is not str or _HEX.fullmatch(sha) is None:
                raise IdentityRefused("invalid SHA256")

def same_process(expected: ProcessObservation, observed: ProcessObservation) -> bool:
    """Conservative comparison; only for planning a separate cooperative stop."""
    if not isinstance(expected, ProcessObservation) or not isinstance(observed, ProcessObservation):
        return False
    if expected.pid != observed.pid or expected.uid != observed.uid:
        return False
    if expected.start_ns != observed.start_ns:
        return False
    if expected.loopback_port != observed.loopback_port:
        return False
    if expected.port_owner_pid != observed.port_owner_pid:
        return False
    if expected.executable_path != observed.executable_path or expected.script_path != observed.script_path:
        return False
    return (hmac.compare_digest(expected.executable_sha256, observed.executable_sha256)
            and hmac.compare_digest(expected.script_sha256, observed.script_sha256))

def preflight(expected: ProcessObservation, observed: ProcessObservation, *, signed_release: bool,
              stop_supported: bool) -> str:
    """Return planning decision only, NEVER an instruction to signal a PID."""
    if signed_release is not True:
        raise IdentityRefused("unsigned candidate")
    if stop_supported is not True:
        raise IdentityRefused("cooperative stop unavailable")
    if not same_process(expected, observed):
        raise IdentityRefused("identity changed")
    return "COOPERATIVE_STOP_PREFLIGHT_ONLY"
