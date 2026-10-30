"""Prospective guarded-server lifecycle for the Beta 14 supervisor process.

Construct only in the process retaining the original Popen handle. It is not
imported by the installed Manager or connected to an install button. A first
signed bootstrap of guarded server.py and the launcher remains necessary.
"""
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid

from authenticated_runtime_client import read_runtime_proof
from creative_release import Refused
from creative_transaction import safe_path
from owned_graceful_stop import graceful_stop_owned
from owned_supervisor_binding import bind_owned_launch
from pending_attempt_recovery import acquire_stopped_attempt, require_no_local_listener
from prejournal_intent import begin_attempt
from process_group_inventory import read_owned_group
from process_start_identity import read_start, require_live_owned_handle
from worker_activity_gate import finish_maintenance, _state


class OwnedGuardedLifecycle:
    """One attempt at a time; a returned lease never owns an arbitrary PID."""

    def __init__(self, source, state, supervisor_state, expected_server_sha256,
                 *, port=8765):
        self.source = safe_path(source, directory=True)
        self.state = _state(state)
        self.supervisor_state = supervisor_state
        self.expected_server_sha256 = expected_server_sha256
        if type(port) is not int or not 1024 <= port <= 65535:
            raise Refused('unexpected_server_port')
        self.port = port
        self.transaction_id = None
        self.ticket = None
        self.lock = None
        self.current = None
        self.healthy = False
        self.token = None
        self.start = None

    def _assert_source(self, source):
        if safe_path(source, directory=True) != self.source:
            raise Refused('different_update_source')
        if (hashlib.sha256(safe_path(self.source / 'server.py').read_bytes()).hexdigest()
                != self.expected_server_sha256):
            raise Refused('guarded_server_changed')

    @contextmanager
    def maintenance(self, source):
        self._assert_source(source)
        launch = bind_owned_launch(self.supervisor_state,
                                   expected_server_sha256=self.expected_server_sha256)
        # A newly launched parent may begin listening before its worker has
        # been retained. Wait for an authenticated idle identity before the
        # durable marker, so a startup race cannot strand maintenance.
        deadline = time.monotonic() + 5
        while True:
            try:
                read_runtime_proof(self.port, launch.token,
                                   expected_parent_pid=launch.handle.pid)
                break
            except Refused as exc:
                if (str(exc) not in ('runtime_process_identity_mismatch',
                                     'runtime_proof_unavailable') or
                        time.monotonic() >= deadline):
                    raise
                require_live_owned_handle(launch.handle, launch.start)
                time.sleep(0.05)
        self.transaction_id = uuid.uuid4().hex
        self.ticket = (secrets.token_hex(32) + '\n').encode('ascii')
        begin_attempt(self.state, self.source, self.ticket, self.transaction_id)
        self.current, self.token, self.start = launch.handle, launch.token, launch.start
        # An uncertain stop leaves the private marker in place and prevents a
        # swap; it never falls back to terminating a PID.
        self.lock = graceful_stop_owned(
            source=self.source, state=self.state, handle=self.current,
            recorded_start=self.start, recorded_server_sha256=self.expected_server_sha256,
            token=self.token, ticket=self.ticket, port=self.port)
        try:
            yield self
        finally:
            try:
                self._finish_if_healthy()
            finally:
                self._close_lock()

    @contextmanager
    def resume_maintenance(self, source, identifier):
        self._assert_source(source)
        if self.transaction_id is not None:
            raise Refused('lifecycle_attempt_already_active')
        self.lock = acquire_stopped_attempt(
            self.source, self.state, identifier, listener_absent=require_no_local_listener)
        self.transaction_id, self.ticket = identifier, self.lock.ticket
        try:
            yield self
        finally:
            try:
                self._finish_if_healthy()
            finally:
                self._close_lock()

    def _close_lock(self):
        if self.lock is not None:
            self.lock.close() if hasattr(self.lock, 'close') else self.lock.__exit__(None, None, None)
            self.lock = None

    def assert_stopped(self):
        if self.lock is None or self.lock.fd is None:
            raise Refused('guarded_writers_not_stopped')
        require_no_local_listener(self.port)

    def _spawn(self):
        self.assert_stopped()
        self._assert_source(self.source)
        token = secrets.token_hex(32)
        env = dict(os.environ, RB_UPDATE_PROBE_TOKEN=token,
                   RB_UPDATE_LAUNCH_TICKET=self.ticket[:-1].decode('ascii'),
                   PYTHONDONTWRITEBYTECODE='1')
        log = self.state / ('restart-' + self.transaction_id + '-' + uuid.uuid4().hex + '.log')
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            # The guarded child must acquire update.lock shared. The ticket
            # keeps all unrelated launches excluded during this handoff.
            self.lock.release_to_ticketed_candidate()
            self.lock = None
            try:
                proc = subprocess.Popen([sys.executable, '-u', str(self.source / 'server.py')],
                    cwd=self.source, env=env, stdin=subprocess.DEVNULL, stdout=fd,
                    stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
            except OSError as exc:
                raise Refused('owned_candidate_spawn_failed') from exc
        finally:
            os.close(fd)
        self.current, self.token, self.start = proc, token, None
        self.supervisor_state.update(process=proc, runtime_token=token,
            server_sha256=self.expected_server_sha256, process_start_token=None)
        # Capture ownership separately from HTTP readiness. Even when health
        # fails, rollback must retain enough evidence for a cooperative stop.
        for _ in range(30):
            if proc.poll() is not None:
                break
            try:
                start = read_start(proc.pid)
                require_live_owned_handle(proc, start)
                self.start = start
                self.supervisor_state['process_start_token'] = start
                break
            except Refused:
                time.sleep(0.1)
        return proc

    def _check_health(self, proc):
        if proc.poll() is not None:
            raise Refused('candidate_exited')
        start = read_start(proc.pid)
        require_live_owned_handle(proc, start)
        report = read_runtime_proof(self.port, self.token, expected_parent_pid=proc.pid)
        read_owned_group(manager_pid=os.getpid(), parent_pid=proc.pid,
                         worker_pid=report['worker_pid'])
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            conn.request('GET', '/api/status')
            response = conn.getresponse()
            raw = response.read(4097)
            if (response.status != 200 or
                    response.getheader('Content-Type', '').split(';')[0] != 'application/json' or
                    len(raw) > 4096 or type(json.loads(raw)) is not dict):
                raise Refused('candidate_status_unhealthy')
        finally:
            conn.close()
        require_live_owned_handle(proc, start)
        self.start = start
        self.supervisor_state['process_start_token'] = start
        self.healthy = True
        return True

    def start_and_check(self):
        proc = self._spawn()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                return self._check_health(proc)
            except (Refused, OSError, http.client.HTTPException, ValueError):
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
        self.healthy = False
        return False

    def stop_candidate(self):
        if self.lock is not None and self.lock.fd is not None:
            return
        if self.current is not None and self.current.poll() is not None:
            self.lock = acquire_stopped_attempt(
                self.source, self.state, self.transaction_id,
                listener_absent=lambda: require_no_local_listener(self.port))
            self.healthy = False
            return
        if self.current is None or self.start is None:
            raise Refused('owned_candidate_identity_unavailable')
        deadline = time.monotonic() + 3
        while True:
            try:
                self.lock = graceful_stop_owned(
                    source=self.source, state=self.state, handle=self.current,
                    recorded_start=self.start,
                    recorded_server_sha256=self.expected_server_sha256,
                    token=self.token, ticket=self.ticket, port=self.port)
                break
            except Refused as exc:
                # The authenticated health GET can briefly retain the shared
                # admission lock after its response. Only this transient lock
                # conflict is retried; changed ownership or active work is
                # never overridden with a process signal.
                if str(exc) != 'worker_busy_or_maintenance' or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        self.healthy = False

    def _finish_if_healthy(self):
        if self.healthy is not True or self.current is None or self.start is None:
            return
        require_live_owned_handle(self.current, self.start)
        report = read_runtime_proof(self.port, self.token,
                                    expected_parent_pid=self.current.pid)
        read_owned_group(manager_pid=os.getpid(), parent_pid=self.current.pid,
                         worker_pid=report['worker_pid'])
        finish_maintenance(self.state, self.ticket,
                           expected_transaction_id=self.transaction_id,
                           owned_health_verified=True, require_intent=True)
