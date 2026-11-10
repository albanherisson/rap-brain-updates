"""Conservative shutdown capability policy; no I/O and no process signals."""
from dataclasses import dataclass
class ShutdownRefused(ValueError): pass
@dataclass(frozen=True)
class Capabilities:
    source_verified: bool
    threaded_http_servers: int
    serve_forever_calls: int
    direct_shutdown_calls: int
    kill_calls: int
    terminate_calls: int
    authenticated_shutdown_endpoint: bool
    external_supervisor: bool

def decide(cap):
    if not isinstance(cap,Capabilities) or cap.source_verified is not True:
        raise ShutdownRefused("Unknown source identity")
    if cap.authenticated_shutdown_endpoint is not True:
        raise ShutdownRefused("Authenticated cooperative stop is unavailable")
    if cap.external_supervisor is not True:
        raise ShutdownRefused("External supervisor required")
    if cap.threaded_http_servers < 1 or cap.serve_forever_calls < 1:
        raise ShutdownRefused("Unexpected server implementation")
    return "COOPERATIVE_ENDPOINT_ONLY_NO_PID_SIGNAL"

def observed_manager():
    """Previously verified AST count observations, not runtime guarantees."""
    return Capabilities(True,1,1,0,2,0,False,False)
