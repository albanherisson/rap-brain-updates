"""End-to-end disposable HTTP stop -> confined update -> health/rollback.

Never invokes a real Manager, installed app, fixed PID or non-loopback port.
Approvals are fixture booleans and DO NOT replace production cryptographic checks.
"""
import hashlib
from fixture_authenticated_http import FixtureServer,authenticated_stop
from fixture_supervisor_preflight import FixtureApproval,run_preflighted_fixture

def update_fixture(root,candidate,secret,*,health,signed=True,identity=True):
    if signed is not True or identity is not True:
        raise ValueError("unverified fixture preflight")
    server=FixtureServer(secret)
    port=server.start()
    try:
        authenticated_stop(server,secret,port)
        approval=FixtureApproval(hashlib.sha256(candidate).hexdigest(),True,signed,identity)
        return run_preflighted_fixture(root,candidate,approval,healthy=health)
    finally:
        server.stop_as_owner()
