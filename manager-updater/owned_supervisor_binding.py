"""Bind Beta 14's retained launch state to a signed server requirement.

Read-only. This must be called in the same Manager supervisor process that
created the Popen handle; a copied PID or a restarted Manager cannot attach.
"""
import re
from dataclasses import dataclass

from creative_release import Refused
from process_start_identity import require_live_owned_handle


@dataclass(frozen=True)
class OwnedLaunch:
    handle: object
    token: str
    start: str
    server_sha256: str


def bind_owned_launch(supervisor_state, *, expected_server_sha256):
    if type(supervisor_state) is not dict:
        raise Refused('owned_supervisor_state_required')
    handle = supervisor_state.get('process')
    token = supervisor_state.get('runtime_token')
    start = supervisor_state.get('process_start_token')
    server_sha = supervisor_state.get('server_sha256')
    if (type(token) is not str or not re.fullmatch(r'[0-9a-f]{64}', token) or
            type(start) is not str or not start or
            type(expected_server_sha256) is not str or
            not re.fullmatch(r'[0-9a-f]{64}', expected_server_sha256) or
            server_sha != expected_server_sha256):
        raise Refused('owned_launch_metadata_missing_or_changed')
    require_live_owned_handle(handle, start)
    return OwnedLaunch(handle, token, start, server_sha)
