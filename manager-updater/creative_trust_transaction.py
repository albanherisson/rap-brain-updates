"""Offline trust rotation for an already guarded Beta 14 app.

Requires an external, Manager-signed manifest and a stopped app/server. It
keeps the guarded server's exclusive lifetime lock and maintenance marker
until the app is signed or exactly restored. It never modifies source/data.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import uuid

from app_bundle_backup import inventory, read_app_backup, restore_app_backup, save_app_backup
from creative_release import Refused
from creative_trust_rotation import digest, verify_rotation
from creative_transaction import Transaction, atomic_write, fsync_dir, safe_path
from mac_offline_bootstrap_gate import (assert_offline, resign_verified_app,
                                        verify_restored_app, verify_unchanged_app)
from strict_json import parse_signed_json
from worker_activity_gate import _lock, _state, begin_maintenance

SERVER_SHA256 = 'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27'


class OfflineTrustRotation:
    def __init__(self, source, launcher, state, *, inspector=None,
                 signer=resign_verified_app, restored_verifier=verify_restored_app,
                 candidate_verifier=verify_unchanged_app):
        self.source = safe_path(source, directory=True)
        self.launcher = safe_path(launcher)
        self.app = self.launcher.parents[2]
        if self.app.suffix != '.app' or self.launcher.parent.name != 'Resources':
            raise Refused('trust_rotation_app_layout')
        self.target = self.launcher.parent / 'creative_release.py'
        self.state = Path(state).absolute()
        if self.source == self.state or self.source.is_relative_to(self.state) or self.state.is_relative_to(self.source):
            raise Refused('trust_rotation_state_overlaps_source')
        self.inspector = inspector
        self.signer = signer
        self.restored_verifier = restored_verifier
        self.candidate_verifier = candidate_verifier

    def _offline(self):
        if self.inspector is None:
            return assert_offline(self.source, self.launcher)
        return assert_offline(self.source, self.launcher, inspector=self.inspector)

    def _record(self, record, phase):
        atomic_write(self.state / 'trust-rotation.json',
                     json.dumps(record | {'phase': phase}, sort_keys=True).encode())

    def _pending(self):
        path = self.state / 'trust-rotation.json'
        if not os.path.lexists(path):
            return None
        raw = safe_path(path).read_bytes()
        if len(raw) > 8192:
            raise Refused('trust_rotation_journal_size')
        try:
            value = json.loads(raw)
        except ValueError as exc:
            raise Refused('trust_rotation_journal_invalid') from exc
        if (type(value) is not dict or set(value) !=
                {'id', 'source', 'launcher', 'phase', 'baseline_sha256', 'candidate_sha256'} or
                type(value['id']) is not str or len(value['id']) != 32 or
                any(c not in '0123456789abcdef' for c in value['id']) or
                value['source'] != str(self.source) or value['launcher'] != str(self.launcher) or
                value['phase'] not in ('preparing', 'backup_ready', 'switch_pending',
                                       'switched', 'committed', 'rolled_back') or
                any(type(value[k]) is not str or len(value[k]) != 64 or
                    any(c not in '0123456789abcdef' for c in value[k])
                    for k in ('baseline_sha256', 'candidate_sha256'))):
            raise Refused('trust_rotation_journal_invalid')
        return value

    def _marker(self, record):
        folder = safe_path(self.state / record['id'], directory=True)
        ticket = safe_path(folder / 'ticket').read_bytes()
        if (len(ticket) != 65 or ticket[-1:] != b'\n' or
                hashlib.sha256(ticket).hexdigest() !=
                safe_path(folder / 'ticket.sha256').read_text('ascii')):
            raise Refused('trust_rotation_ticket_changed')
        marker = safe_path(self.state / 'maintenance.ticket').read_bytes()
        if marker != ticket:
            raise Refused('trust_rotation_marker_changed')
        return folder, ticket

    def _finish(self, record, ticket):
        self._offline()
        current = self._pending()
        if current is None or any(current.get(key) != value for key, value in record.items()
                                  if key != 'phase'):
            raise Refused('trust_rotation_journal_changed')
        if safe_path(self.state / 'maintenance.ticket').read_bytes() != ticket:
            raise Refused('trust_rotation_marker_changed')
        if current['phase'] not in ('committed', 'rolled_back'):
            raise Refused('trust_rotation_not_terminal')
        (self.state / 'maintenance.ticket').unlink()
        fsync_dir(self.state)

    def _restore(self, record, folder, ticket):
        expected = read_app_backup(folder)
        original = safe_path(folder / 'app-original.app' / 'Contents' / 'Resources' /
                             'creative_release.py').read_bytes()
        if digest(original) != record['baseline_sha256']:
            raise Refused('trust_rotation_backup_changed')
        raw = safe_path(folder / 'signed-manifest.json').read_bytes()
        signed_payload = parse_signed_json(raw)['signed_payload']
        signed, candidate = verify_rotation(raw, original, now=signed_payload['issued_at'])
        if digest(candidate) != record['candidate_sha256']:
            raise Refused('trust_rotation_journal_candidate_changed')
        current = digest(safe_path(self.target).read_bytes())
        if current not in (record['baseline_sha256'], record['candidate_sha256']):
            raise Refused('trust_rotation_unknown_live_code')
        self._offline()
        restore_app_backup(self.app, folder,
                           allowed_extra=('Contents/_CodeSignature/CodeResources',))
        if inventory(self.app) != expected:
            raise Refused('trust_rotation_rollback_changed')
        args = {'inspector': self.inspector} if self.inspector else {}
        if self.restored_verifier(self.app, folder, self.source, self.launcher, **args) is not True:
            raise Refused('trust_rotation_restore_signature')
        self._record(record, 'rolled_back')
        self._finish(record, ticket)
        return {'state': 'rolled_back', 'installation_performed': False}

    def _verify_candidate_app(self, folder, candidate_hash):
        original = read_app_backup(folder)
        current = inventory(self.app)
        allowed = {'Contents/Resources/creative_release.py',
                   'Contents/_CodeSignature/CodeResources'}
        if (set(current) - set(original) - allowed or
                set(original) - set(current) - allowed or
                current.get('Contents/Resources/creative_release.py', {}).get('sha256') !=
                    candidate_hash or
                any(current[name]['sha256'] != entry['sha256']
                    for name, entry in original.items() if name not in allowed)):
            raise Refused('trust_rotation_unexpected_app_change')
        args = {'inspector': self.inspector} if self.inspector else {}
        if self.candidate_verifier(self.app, self.source, self.launcher, **args) is not True:
            raise Refused('trust_rotation_candidate_signature')

    def install(self, manifest):
        self._offline()
        state = _state(self.state)
        # update.lock is the lifetime lock of the already guarded server.
        lock = _lock(state, 'update.lock', fcntl.LOCK_EX)
        try:
            self._offline()
            pending = self._pending()
            if pending is not None:
                if (pending['phase'] == 'preparing' and
                        not os.path.lexists(state / 'maintenance.ticket')):
                    if digest(safe_path(self.target).read_bytes()) != pending['baseline_sha256']:
                        raise Refused('trust_rotation_unbacked_change')
                    self._record(pending, 'rolled_back')
                    return {'state': 'rolled_back', 'installation_performed': False}
                if pending['phase'] in ('committed', 'rolled_back'):
                    if os.path.lexists(state / 'maintenance.ticket'):
                        folder, ticket = self._marker(pending)
                        if pending['phase'] == 'rolled_back':
                            return self._restore(pending, folder, ticket)
                        if digest(safe_path(self.target).read_bytes()) != pending['candidate_sha256']:
                            raise Refused('trust_rotation_committed_code_changed')
                        self._verify_candidate_app(folder, pending['candidate_sha256'])
                        self._finish(pending, ticket)
                        return {'state': 'committed', 'installation_performed': True,
                                'backup_id': pending['id'], 'recovered': True,
                                'database_modified': False}
                    if pending['phase'] == 'committed':
                        folder = safe_path(state / pending['id'], directory=True)
                        self._verify_candidate_app(folder, pending['candidate_sha256'])
                        return {'state': 'committed', 'installation_performed': False,
                                'already_installed': True, 'backup_id': pending['id'],
                                'database_modified': False}
                    raise Refused('trust_rotation_previous_rollback')
                folder, ticket = self._marker(pending)
                if pending['phase'] == 'preparing' and not (folder / 'app-backup.json').is_file():
                    if digest(safe_path(self.target).read_bytes()) != pending['baseline_sha256']:
                        raise Refused('trust_rotation_unbacked_change')
                    self._record(pending, 'rolled_back')
                    self._finish(pending, ticket)
                    return {'state': 'rolled_back', 'installation_performed': False}
                return self._restore(pending, folder, ticket)
            if os.path.lexists(state / 'maintenance.ticket'):
                raise Refused('trust_rotation_foreign_maintenance')
            original = safe_path(self.target).read_bytes()
            signed, candidate = verify_rotation(manifest, original)
            if digest(safe_path(self.source / 'server.py').read_bytes()) != SERVER_SHA256:
                raise Refused('trust_rotation_server_changed')
            identifier = uuid.uuid4().hex
            folder = state / identifier
            folder.mkdir(mode=0o700)
            fsync_dir(state)
            ticket = (secrets.token_hex(32) + '\n').encode('ascii')
            atomic_write(folder / 'ticket', ticket)
            atomic_write(folder / 'ticket.sha256', hashlib.sha256(ticket).hexdigest().encode())
            atomic_write(folder / 'signed-manifest.json', manifest)
            record = {'id': identifier, 'source': str(self.source),
                      'launcher': str(self.launcher),
                      'baseline_sha256': digest(original),
                      'candidate_sha256': digest(candidate)}
            self._record(record, 'preparing')
            begin_maintenance(state, ticket)
            try:
                self._offline()
                save_app_backup(self.app, folder)
                Transaction(self.source, state).backup(folder,
                    safe_path(self.source / 'creative_engine.py').read_bytes())
                self._record(record, 'backup_ready')
                if safe_path(self.target).read_bytes() != original:
                    raise Refused('trust_rotation_baseline_changed')
                self._record(record, 'switch_pending')
                mode = stat.S_IMODE(self.target.stat().st_mode)
                atomic_write(self.target, candidate, mode)
                self._record(record, 'switched')
                self._offline()
                args = {'inspector': self.inspector} if self.inspector else {}
                if self.signer(self.app, folder, self.source, self.launcher, **args) is not True:
                    raise Refused('trust_rotation_app_signature')
                if digest(safe_path(self.target).read_bytes()) != signed['candidate_sha256']:
                    raise Refused('trust_rotation_candidate_changed')
                self._verify_candidate_app(folder, signed['candidate_sha256'])
            except Exception:
                if (folder / 'app-backup.json').is_file():
                    return self._restore(record, folder, ticket)
                # No app bytes were replaced before the backup completed.
                if safe_path(self.target).read_bytes() != original:
                    raise Refused('trust_rotation_unbacked_change')
                self._record(record, 'rolled_back')
                self._finish(record, ticket)
                raise
            self._record(record, 'committed')
            self._finish(record, ticket)
            return {'state': 'committed', 'installation_performed': True,
                    'backup_id': identifier, 'database_modified': False}
        finally:
            os.close(lock)
