"""One-time external bootstrap lifecycle; never attaches to an old server PID.

The old unguarded server and Beta 14 app must already be offline. Candidate
restart uses a fresh owned Popen handle and ticket; uncertain identity refuses
and retains the recovery marker. A restored original remains stopped, then its
marker can be cleared after exact backup and signature verification.

This is not connected to a downloadable installer or installed Manager. Its
macOS process census, app re-signing and real-server restart need owner-side
validation before production use.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import uuid

from app_bundle_backup import read_app_backup
from bootstrap_full_release import FILES
from bootstrap_runtime_resources import RUNTIME_FILES
from creative_release import Refused, digest
from creative_transaction import atomic_write, fsync_dir, safe_path
from mac_final_readonly_probe import coarse_process_inventory
from mac_offline_bootstrap_gate import (assert_offline, resign_verified_app,
                                        verify_restored_app, verify_unchanged_app)
from owned_graceful_stop import graceful_stop_owned
from owned_guarded_lifecycle import OwnedGuardedLifecycle
from pending_attempt_recovery import _private_json
from worker_activity_gate import _lock, _state, begin_maintenance


class LifetimeLock:
    def __init__(self, fd):
        self.fd = fd

    def release_to_ticketed_candidate(self):
        if self.fd is None:
            raise Refused('bootstrap_lifetime_lock_released')
        os.close(self.fd)
        self.fd = None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class MacOfflineBootstrapLifecycle:
    def __init__(self, source, launcher, state, manifest, *, port=8765,
                 inspector=coarse_process_inventory, signer=resign_verified_app,
                 restored_verifier=verify_restored_app,
                 unchanged_verifier=verify_unchanged_app,
                 candidate_factory=OwnedGuardedLifecycle):
        self.source = safe_path(source, directory=True)
        self.launcher = safe_path(launcher)
        self.app = self.launcher.parents[2]
        if self.app.suffix != '.app' or self.launcher.parent.name != 'Resources':
            raise Refused('bootstrap_app_layout_unknown')
        self.state = Path(state).absolute()
        if (type(manifest) is not dict or manifest.get('schema') !=
                'rapbrain-guarded-bootstrap-v2' or
                any(type(manifest.get(name)) is not str or
                    len(manifest[name]) != 64 or
                    any(c not in '0123456789abcdef' for c in manifest[name])
                    for name in ('baseline_server_sha256', 'candidate_server_sha256',
                                 'baseline_launcher_sha256', 'candidate_launcher_sha256',
                                 'baseline_dashboard_sha256', 'candidate_dashboard_sha256')) or
                type(manifest.get('runtime_sha256')) is not dict or
                manifest['runtime_sha256'].keys() != set(RUNTIME_FILES)):
            raise Refused('bootstrap_verified_manifest_required')
        if type(port) is not int or not 1024 <= port <= 65535:
            raise Refused('bootstrap_port_invalid')
        self.manifest = manifest
        self.port = port
        self.inspector = inspector
        self.signer = signer
        self.restored_verifier = restored_verifier
        self.unchanged_verifier = unchanged_verifier
        self.candidate_factory = candidate_factory
        self.transaction_id = None
        self.ticket = None
        self.lock = None
        self.owned = None
        self.supervisor_state = {}
        self.app_signed = False

    def _identity(self, source, launcher):
        if (safe_path(source, directory=True) != self.source or
                safe_path(launcher) != self.launcher):
            raise Refused('bootstrap_source_changed')

    def _offline(self):
        return assert_offline(self.source, self.launcher, inspector=self.inspector)

    def _acquire_lock(self):
        fd = _lock(self.state, 'update.lock', fcntl.LOCK_EX)
        self.lock = LifetimeLock(fd)
        try:
            self._offline()
        except BaseException:
            self.lock.close()
            self.lock = None
            raise

    @contextmanager
    def maintenance(self, source, launcher):
        self._identity(source, launcher)
        self.state = _state(self.state)
        self._offline()
        self._acquire_lock()
        self.transaction_id = uuid.uuid4().hex
        self.ticket = (secrets.token_hex(32) + '\n').encode('ascii')
        try:
            if any(os.path.lexists(self.state / name) for name in
                   ('bootstrap-intent.json', 'maintenance.ticket', 'maintenance-intent.json')):
                raise Refused('bootstrap_previous_attempt_pending')
            intent = {'id': self.transaction_id, 'source': str(self.source),
                      'launcher': str(self.launcher),
                      'ticket_sha256': hashlib.sha256(self.ticket).hexdigest()}
            atomic_write(self.state / 'bootstrap-intent.json',
                         json.dumps(intent, sort_keys=True).encode())
            begin_maintenance(self.state, self.ticket)
            self._offline()
            yield self
        finally:
            try:
                self._finalize_terminal()
            finally:
                if self.lock is not None:
                    self.lock.close()
                    self.lock = None

    @contextmanager
    def resume_maintenance(self, source, launcher, identifier):
        self._identity(source, launcher)
        self.state = _state(self.state)
        self._offline()
        self._acquire_lock()
        try:
            intent = _private_json(self.state / 'bootstrap-intent.json', 4096)
            ticket = safe_path(self.state / 'maintenance.ticket').read_bytes()
            if (type(identifier) is not str or len(identifier) != 32 or
                    any(c not in '0123456789abcdef' for c in identifier) or
                    type(intent) is not dict or intent.keys() !=
                    {'id', 'source', 'launcher', 'ticket_sha256'} or
                    intent['id'] != identifier or intent['source'] != str(self.source) or
                    intent['launcher'] != str(self.launcher) or
                    len(ticket) != 65 or ticket[-1:] != b'\n' or
                    any(c not in b'0123456789abcdef' for c in ticket[:-1]) or
                    intent['ticket_sha256'] != hashlib.sha256(ticket).hexdigest()):
                raise Refused('bootstrap_original_attempt_changed')
            self.transaction_id, self.ticket = identifier, ticket
            yield self
        finally:
            try:
                self._finalize_terminal()
            finally:
                if self.lock is not None:
                    self.lock.close()
                    self.lock = None

    def assert_stopped(self):
        if self.lock is None or self.lock.fd is None:
            raise Refused('bootstrap_writers_not_stopped')
        self._offline()

    def _sign(self):
        self.assert_stopped()
        folder = safe_path(self.state / self.transaction_id, directory=True)
        current = digest(safe_path(self.source / 'server.py').read_bytes())
        if current == self.manifest['candidate_server_sha256']:
            read_app_backup(folder)
            verified = self.signer(self.app, folder, self.source, self.launcher,
                                   inspector=self.inspector)
        elif current == self.manifest['baseline_server_sha256']:
            if (folder / 'app-backup.json').is_file():
                verified = self.restored_verifier(self.app, folder, self.source,
                                                  self.launcher, inspector=self.inspector)
            else:
                verified = self.unchanged_verifier(self.app, self.source,
                                                   self.launcher, inspector=self.inspector)
        else:
            raise Refused('bootstrap_server_changed_before_signature')
        if verified is not True:
            raise Refused('bootstrap_app_signature_unverified')
        self.app_signed = True

    def start_and_check(self):
        self._sign()
        current = digest(safe_path(self.source / 'server.py').read_bytes())
        if current == self.manifest['baseline_server_sha256']:
            # The original unguarded server cannot provide an authenticated
            # update health proof. Leave restored code stopped; the terminal
            # journal can permit a later ordinary launch.
            return False
        if current != self.manifest['candidate_server_sha256']:
            raise Refused('bootstrap_server_changed_before_restart')
        self.owned = self.candidate_factory(self.source, self.state,
            self.supervisor_state, current, port=self.port)
        self.owned.transaction_id = self.transaction_id
        self.owned.ticket = self.ticket
        self.owned.lock = self.lock
        try:
            return self.owned.start_and_check()
        finally:
            # The candidate has released the exclusive lock for its shared
            # lifetime guard. A failed start never permits an unowned stop.
            if self.lock is not None and self.lock.fd is None:
                self.lock = None

    def stop_candidate(self):
        if self.owned is None:
            self.assert_stopped()
            return
        proc = self.owned.current
        if proc is None:
            self._acquire_lock()
            self.owned = None
            self.assert_stopped()
            return
        if proc.poll() is not None:
            self._acquire_lock()
        else:
            if self.owned.start is None:
                raise Refused('bootstrap_candidate_start_unknown')
            deadline = time.monotonic() + 3
            while True:
                try:
                    self.lock = graceful_stop_owned(
                        source=self.source, state=self.state, handle=proc,
                        recorded_start=self.owned.start,
                        recorded_server_sha256=self.manifest['candidate_server_sha256'],
                        token=self.owned.token, ticket=self.ticket, port=self.port)
                    break
                except Refused as exc:
                    if str(exc) != 'worker_busy_or_maintenance' or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
        self.owned = None
        self.assert_stopped()

    def _finalize_terminal(self):
        journal = self.state / 'bootstrap-transaction.json'
        if not journal.is_file() or self.transaction_id is None:
            return
        record = _private_json(journal, 8192)
        if (type(record) is not dict or record.get('id') != self.transaction_id or
                record.get('source') != str(self.source) or
                record.get('launcher') != str(self.launcher) or
                record.get('phase') not in ('committed', 'restored_stopped', 'aborted')):
            return
        if self.owned is not None:
            self.stop_candidate()
        self.assert_stopped()
        if not self.app_signed:
            return
        expected = ('candidate' if record['phase'] == 'committed' else 'baseline')
        for kind, path in (('server', self.source / 'server.py'),
                           ('launcher', self.launcher),
                           ('dashboard', self.launcher.parent / 'dashboard_beta14.html')):
            if digest(safe_path(path).read_bytes()) != self.manifest[
                    expected + '_' + kind + '_sha256']:
                raise Refused('bootstrap_terminal_code_changed')
        if record['phase'] != 'committed':
            if any(os.path.lexists(self.launcher.parent / name) for name in FILES[3:]):
                raise Refused('bootstrap_terminal_runtime_changed')
        else:
            for name, expected_hash in self.manifest['runtime_sha256'].items():
                if (type(expected_hash) is not str or
                        digest(safe_path(self.launcher.parent / name).read_bytes()) !=
                        expected_hash):
                    raise Refused('bootstrap_terminal_runtime_changed')
        marker = safe_path(self.state / 'maintenance.ticket')
        intent = _private_json(self.state / 'bootstrap-intent.json', 4096)
        if (marker.read_bytes() != self.ticket or intent.get('id') != self.transaction_id or
                intent.get('ticket_sha256') != hashlib.sha256(self.ticket).hexdigest()):
            raise Refused('bootstrap_terminal_ticket_changed')
        marker.unlink()
        (self.state / 'bootstrap-intent.json').unlink()
        fsync_dir(self.state)
