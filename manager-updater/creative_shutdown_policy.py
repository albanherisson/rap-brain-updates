"""Pure fail-closed policy for a future Manager-owned Rap Brain shutdown.

This module never discovers, starts, signals or waits on a process. Its inputs
must be collected by a reviewed authenticated endpoint and OS process-group
inventory after HTTP admission has been closed and in-flight requests drained.
"""
from dataclasses import dataclass
from creative_release import Refused
from creative_readiness import TERMINAL


@dataclass(frozen=True)
class RuntimeProof:
    parent_pid: int
    worker_pid: int
    parent_start_token: str
    worker_start_token: str
    parent_script_sha256: str
    worker_script_sha256: str
    audio_pid: int | None
    process_group_pids: frozenset[int]
    authenticated_parent: bool
    parent_owned_handle_alive: bool
    worker_same_script: bool
    worker_idle_verified: bool
    audio_idle_verified: bool
    admission_marker_held: bool
    http_requests_drained: bool
    job_status_counts: dict[str, int]


def assert_safe_to_stop(proof: RuntimeProof, *, owned_pid: int,
                        owned_start_token: str, expected_server_sha256: str):
    if not isinstance(proof, RuntimeProof):
        raise Refused('runtime_proof_required')
    if (type(owned_pid) is not int or owned_pid < 2 or
            type(proof.parent_pid) is not int or proof.parent_pid != owned_pid or
            type(proof.worker_pid) is not int or proof.worker_pid < 2 or
            proof.worker_pid == owned_pid):
        raise Refused('owned_process_identity_missing')
    if (proof.authenticated_parent is not True or
            proof.parent_owned_handle_alive is not True or
            proof.worker_same_script is not True or
            proof.worker_idle_verified is not True):
        raise Refused('process_ownership_unverified')
    # The retained Popen PID alone cannot distinguish a reused PID. The
    # start token must come from the OS for that exact handle and be compared
    # with a fresh OS inventory immediately before the signal. The worker
    # must run the same pinned server source as its parent.
    if (type(owned_start_token) is not str or not owned_start_token or
            type(proof.parent_start_token) is not str or
            proof.parent_start_token != owned_start_token or
            type(proof.worker_start_token) is not str or not proof.worker_start_token or
            proof.worker_start_token == proof.parent_start_token):
        raise Refused('process_start_identity_changed')
    if (type(expected_server_sha256) is not str or
            len(expected_server_sha256) != 64 or
            any(c not in '0123456789abcdef' for c in expected_server_sha256) or
            proof.parent_script_sha256 != expected_server_sha256 or
            proof.worker_script_sha256 != expected_server_sha256):
        raise Refused('server_script_identity_changed')
    if proof.admission_marker_held is not True or proof.http_requests_drained is not True:
        raise Refused('admission_not_quiescent')
    if proof.audio_idle_verified is not True or proof.audio_pid is not None:
        raise Refused('audio_capture_active_or_unknown')
    if (type(proof.process_group_pids) is not frozenset or
            proof.process_group_pids != frozenset((owned_pid, proof.worker_pid))):
        raise Refused('unexpected_process_in_server_group')
    if type(proof.job_status_counts) is not dict:
        raise Refused('job_states_unverified')
    for status, count in proof.job_status_counts.items():
        if (type(status) is not str or status not in TERMINAL or
                type(count) is not int or count < 0):
            raise Refused('jobs_active_or_unknown_status')
    return True
