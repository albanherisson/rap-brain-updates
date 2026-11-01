"""Disposable authenticated cooperative-stop simulation. No OS signals or sockets.

A real Manager is NEVER an accepted target. This module only models a
one-time challenge/response and transactional stop/upgrade/recovery.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from pathlib import Path
from external_supervisor_fixture import MARKER,run

class Rejected(RuntimeError): pass
@dataclass
class DummyServer:
    secret: bytes
    alive: bool=True
    used: bool=False
    def response(self,challenge):
        if not self.alive or self.used:raise Rejected("unavailable")
        return hmac.new(self.secret,b"rapbrain-fixture-stop-v1:"+challenge,hashlib.sha256).digest()
    def cooperative_stop(self,challenge,proof):
        if not self.alive or self.used:raise Rejected("stopped or replayed")
        expected=self.response(challenge)
        if not hmac.compare_digest(expected,proof):raise Rejected("unauthenticated")
        self.used=True
        self.alive=False
        return True

def fixture_transaction(root,server,supervisor_secret,*,signed=True,health=True,crash=None):
    root=Path(root).absolute()
    if root.name!="DisposableSupervisorFixture" or root.is_symlink():
        raise Rejected("only disposable test fixture")
    if (root/"fixture.marker").read_bytes()!=MARKER:
        raise Rejected("missing test fixture marker")
    if signed is not True:raise Rejected("signature verification missing")
    if type(supervisor_secret) is not bytes or len(supervisor_secret)<32:
        raise Rejected("invalid secret")
    if not isinstance(server,DummyServer):raise Rejected("no dummy server")
    challenge=secrets.token_bytes(32)
    expected=hmac.new(supervisor_secret,b"rapbrain-fixture-stop-v1:"+challenge,hashlib.sha256).digest()
    actual=server.response(challenge)
    if not hmac.compare_digest(expected,actual):
        raise Rejected("server failed authentication")
    server.cooperative_stop(challenge,expected)
    return run(root,health=health,crash=crash)
