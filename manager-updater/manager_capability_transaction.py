"""Offline, one-time installation of a signed Manager capability.

Only a stopped app and the private helper may change. The SQLite and Ollama
configuration backups are verified but are never restored over live data.
Pending work always recovers the original app from the same authenticated
attempt; it never downloads a fresh publication during recovery.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import stat
import uuid

from app_bundle_backup import inventory, read_app_backup, restore_app_backup, save_app_backup
from creative_release import Refused, digest
from creative_transaction import Transaction, atomic_write, fsync_dir, safe_path
from mac_offline_bootstrap_gate import (assert_offline, resign_verified_app,
                                        verify_restored_app, verify_unchanged_app)
from manager_capability_inventory import APP_CODE_FILES, APP_SUPPORT_FILES
from manager_capability_release import verify_release
from manager_helper_release import (stage_verified, verify_archive as verify_helper_archive,
                                    verify_manifest as verify_helper_manifest, verify_staged)
from pending_attempt_recovery import _private_json
from strict_json import parse_signed_json
from worker_activity_gate import _lock, _state, begin_maintenance


TERMINAL = {'committed', 'rolled_back'}
PHASES = TERMINAL | {'preparing', 'backup_ready', 'helper_staged',
                     'marker_ready', 'switch_pending', 'switched'}


class OfflineManagerCapability:
    def __init__(self, source, launcher, state, *, inspector=None,
                 signer=resign_verified_app, restored_verifier=verify_restored_app,
                 original_verifier=verify_unchanged_app, pinned_key=None):
        self.source = safe_path(source, directory=True)
        self.launcher = safe_path(launcher)
        self.app = self.launcher.parents[2]
        if self.app.suffix != '.app' or self.launcher.parent.name != 'Resources':
            raise Refused('manager_capability_app_layout')
        self.resources = self.launcher.parent
        self.state = _state(state)
        if (self.state == self.source or self.state.is_relative_to(self.source) or
                self.source.is_relative_to(self.state) or
                self.state.is_relative_to(self.app) or
                self.app.is_relative_to(self.state)):
            raise Refused('manager_capability_state_overlap')
        self.inspector = inspector
        self.signer = signer
        self.restored_verifier = restored_verifier
        self.original_verifier = original_verifier
        if pinned_key is None:
            from bootstrap_release import PUBLISHER_PIN
            pinned_key = PUBLISHER_PIN
        self.pin = pinned_key
        self.journal = self.state / 'manager-capability.json'

    def _offline(self):
        opts = {'inspector': self.inspector} if self.inspector else {}
        return assert_offline(self.source, self.launcher, **opts)

    def _verify_app(self, verifier, *args):
        opts = {'inspector': self.inspector} if self.inspector else {}
        if verifier(*args, self.source, self.launcher, **opts) is not True:
            raise Refused('manager_capability_app_signature')

    def _record(self, record, phase):
        atomic_write(self.journal, json.dumps(record | {'phase': phase},
                                               sort_keys=True).encode())

    def _pending(self):
        if not os.path.lexists(self.journal):
            return None
        record = _private_json(self.journal, 4096)
        if (type(record) is not dict or record.keys() !=
                {'id', 'phase', 'source', 'launcher', 'release_sha256',
                 'archive_sha256', 'ticket_sha256', 'helper_sha256'} or
                type(record['id']) is not str or len(record['id']) != 32 or
                any(c not in '0123456789abcdef' for c in record['id']) or
                record['phase'] not in PHASES or
                record['source'] != str(self.source) or
                record['launcher'] != str(self.launcher) or
                any(type(record[k]) is not str or len(record[k]) != 64 or
                    any(c not in '0123456789abcdef' for c in record[k])
                    for k in ('release_sha256', 'archive_sha256',
                              'ticket_sha256', 'helper_sha256'))):
            raise Refused('manager_capability_journal_invalid')
        return record

    def _folder(self, record):
        folder = safe_path(self.state / record['id'], directory=True)
        if folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077:
            raise Refused('manager_capability_backup_unsafe')
        raw = safe_path(folder / 'signed-release.json').read_bytes()
        archive = safe_path(folder / 'capability.zip').read_bytes()
        if (digest(raw) != record['release_sha256'] or
                digest(archive) != record['archive_sha256']):
            raise Refused('manager_capability_saved_release_changed')
        issued = parse_signed_json(raw)['signed_payload']['issued_at']
        signed, files, helper = verify_release(raw, archive,
                                               pinned_key=self.pin, now=issued)
        return folder, signed, files, helper

    def _ticket(self, folder, record):
        ticket = safe_path(folder / 'ticket').read_bytes()
        if (len(ticket) != 65 or ticket[-1:] != b'\n' or
                hashlib.sha256(ticket).hexdigest() != record['ticket_sha256']):
            raise Refused('manager_capability_ticket_changed')
        marker = self.state / 'maintenance.ticket'
        if os.path.lexists(marker) and safe_path(marker).read_bytes() != ticket:
            raise Refused('manager_capability_marker_changed')
        return ticket

    def _finish(self, folder, record):
        self._offline()
        ticket = self._ticket(folder, record)
        marker = self.state / 'maintenance.ticket'
        if os.path.lexists(marker):
            marker.unlink()
            fsync_dir(self.state)

    def _candidate_inventory(self, original, files):
        current = inventory(self.app)
        if (set(current) - set(original) -
                {'Contents/Resources/' + name for name in APP_SUPPORT_FILES} -
                {'Contents/_CodeSignature/CodeResources'}):
            raise Refused('manager_capability_unexpected_app_entry')
        if set(original) - set(current):
            raise Refused('manager_capability_original_entry_missing')
        try:
            info = plistlib.loads(safe_path(self.app / 'Contents' / 'Info.plist').read_bytes())
            executable = info['CFBundleExecutable']
        except (ValueError, KeyError, TypeError) as exc:
            raise Refused('manager_capability_executable_unknown') from exc
        if (type(executable) is not str or not 1 <= len(executable) <= 100 or
                any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-'
                    for c in executable)):
            raise Refused('manager_capability_executable_unknown')
        allowed = {'Contents/_CodeSignature/CodeResources',
                   'Contents/MacOS/' + executable}
        allowed.update('Contents/Resources/' + name for name in APP_CODE_FILES)
        if (set(current) - set(original) - allowed or
                set(original) - set(current) - allowed or
                any(current[name]['sha256'] != original[name]['sha256']
                    for name in set(original) & set(current) - allowed)):
            raise Refused('manager_capability_unexpected_app_change')
        for name in APP_CODE_FILES:
            target = 'Contents/Resources/' + name
            if current.get(target, {}).get('sha256') != digest(files['app/' + name]):
                raise Refused('manager_capability_candidate_changed')
        self._verify_app(self.original_verifier, self.app)

    def _restore(self, record, folder, files):
        original = read_app_backup(folder)
        current = inventory(self.app)
        allowed = {'Contents/Resources/' + name for name in APP_SUPPORT_FILES}
        allowed.add('Contents/_CodeSignature/CodeResources')
        if set(current) - set(original) - allowed:
            raise Refused('manager_capability_unexpected_extra_preserved')
        # Do not overwrite files modified by another actor while recovery was
        # pending. The signed payload and exact backup bound each code path.
        for name in APP_CODE_FILES:
            key = 'Contents/Resources/' + name
            candidate = digest(files['app/' + name])
            baseline = original.get(key, {}).get('sha256')
            actual = current.get(key, {}).get('sha256')
            if actual not in (baseline, candidate):
                raise Refused('manager_capability_unknown_live_code')
        self._offline()
        restore_app_backup(self.app, folder, allowed_extra=allowed)
        self._verify_app(self.restored_verifier, self.app, folder)
        if inventory(self.app) != original:
            raise Refused('manager_capability_restore_changed')
        return True

    def _remove_helper(self, record, files, helper_signed):
        folder = self.state / 'helper'
        retired = self.state / ('helper-rollback-' + record['id'])
        if not os.path.lexists(folder) and not os.path.lexists(retired):
            return
        if os.path.lexists(folder) and os.path.lexists(retired):
            raise Refused('manager_capability_helper_rollback_conflict')
        from manager_helper_inventory import HELPER_FILES
        if digest(files['helper.zip']) != record['helper_sha256']:
            raise Refused('manager_capability_helper_changed')
        issued = parse_signed_json(helper_signed)['signed_payload']['issued_at']
        manifest = verify_helper_manifest(helper_signed, pinned_key=self.pin,
                                          now=issued)
        members = verify_helper_archive(files['helper.zip'], manifest)
        if os.path.lexists(folder):
            verify_staged(self.state, pinned_key=self.pin)
            os.rename(folder, retired)
            fsync_dir(self.state)
        retired = safe_path(retired, directory=True)
        if retired.stat().st_uid != os.getuid() or retired.stat().st_mode & 0o077:
            raise Refused('manager_capability_helper_rollback_unsafe')
        expected = {'signed-manifest.json': helper_signed} | members
        remaining = set(os.listdir(retired))
        if remaining - set(expected):
            raise Refused('manager_capability_helper_rollback_extra')
        for name in remaining:
            path = safe_path(retired / name)
            if (path.stat().st_uid != os.getuid() or
                    path.stat().st_mode & 0o077 or
                    path.read_bytes() != expected[name]):
                raise Refused('manager_capability_helper_rollback_changed')
        for name in remaining:
            (retired / name).unlink()
        retired.rmdir()
        fsync_dir(self.state)

    def _recover(self, record):
        folder, signed, files, helper = self._folder(record)
        ticket = self._ticket(folder, record)
        if record['phase'] == 'committed':
            self._candidate_inventory(read_app_backup(folder), files)
            verify_staged(self.state, pinned_key=self.pin)
            if not os.path.lexists(self.state / 'maintenance.ticket'):
                return {'state': 'committed', 'installation_performed': False,
                        'already_installed': True, 'backup_id': record['id'],
                        'database_modified': False}
            self._finish(folder, record)
            return {'state': 'committed', 'installation_performed': True,
                    'recovered': True, 'backup_id': record['id'],
                    'database_modified': False}
        if record['phase'] == 'rolled_back':
            if not (folder / 'app-backup.json').is_file():
                if (os.path.lexists(self.state / 'maintenance.ticket') or
                        os.path.lexists(self.state / 'helper') or
                        digest(self.launcher.read_bytes()) !=
                            signed['baseline_launcher_sha256'] or
                        digest(safe_path(self.resources / 'dashboard_beta14.html').read_bytes()) !=
                            signed['baseline_dashboard_sha256']):
                    raise Refused('manager_capability_unbacked_rollback_changed')
                self._verify_app(self.original_verifier, self.app)
                return {'state': 'rolled_back', 'installation_performed': False}
            if inventory(self.app) != read_app_backup(folder):
                raise Refused('manager_capability_rollback_changed')
            if os.path.lexists(self.state / 'helper'):
                raise Refused('manager_capability_helper_after_rollback')
            self._finish(folder, record)
            return {'state': 'rolled_back', 'installation_performed': False}
        if not (folder / 'app-backup.json').is_file():
            if (record['phase'] != 'preparing' or
                    os.path.lexists(self.state / 'helper') or
                    os.path.lexists(self.state / 'maintenance.ticket') or
                    digest(self.launcher.read_bytes()) !=
                        signed['baseline_launcher_sha256']):
                raise Refused('manager_capability_unbacked_attempt')
            self._record(record, 'rolled_back')
            return {'state': 'rolled_back', 'installation_performed': False}
        self._restore(record, folder, files)
        self._remove_helper(record, files, helper)
        self._record(record, 'rolled_back')
        self._finish(folder, record)
        return {'state': 'rolled_back', 'installation_performed': False,
                'recovered': True, 'database_modified': False}

    def install(self, raw=b'', archive=b''):
        self._offline()
        lock = _lock(self.state, 'update.lock', fcntl.LOCK_EX)
        try:
            self._offline()
            record = self._pending()
            if record is not None:
                return self._recover(record)
            if any(os.path.lexists(self.state / name) for name in
                   ('maintenance.ticket', 'bootstrap-intent.json',
                    'maintenance-intent.json', 'helper')):
                raise Refused('manager_capability_foreign_attempt')
            signed, files, helper = verify_release(raw, archive, pinned_key=self.pin)
            if (digest(safe_path(self.source / 'server.py').read_bytes()) !=
                    signed['required_server_sha256'] or
                    digest(self.launcher.read_bytes()) != signed['baseline_launcher_sha256'] or
                    digest(safe_path(self.resources / 'dashboard_beta14.html').read_bytes()) !=
                        signed['baseline_dashboard_sha256'] or
                    any(os.path.lexists(self.resources / name)
                        for name in APP_SUPPORT_FILES)):
                raise Refused('manager_capability_baseline_changed')
            self._verify_app(self.original_verifier, self.app)
            identifier = uuid.uuid4().hex
            folder = self.state / identifier
            folder.mkdir(mode=0o700)
            fsync_dir(self.state)
            ticket = (secrets.token_hex(32) + '\n').encode()
            atomic_write(folder / 'ticket', ticket)
            atomic_write(folder / 'signed-release.json', raw)
            atomic_write(folder / 'capability.zip', archive)
            record = {'id': identifier, 'source': str(self.source),
                      'launcher': str(self.launcher),
                      'release_sha256': digest(raw),
                      'archive_sha256': digest(archive),
                      'ticket_sha256': hashlib.sha256(ticket).hexdigest(),
                      'helper_sha256': digest(files['helper.zip'])}
            self._record(record, 'preparing')
            try:
                self._offline()
                save_app_backup(self.app, folder)
                Transaction(self.source, self.state).backup(folder,
                    safe_path(self.source / 'creative_engine.py').read_bytes())
                self._record(record, 'backup_ready')
                stage_verified(self.state, helper, files['helper.zip'],
                               pinned_key=self.pin)
                self._record(record, 'helper_staged')
                begin_maintenance(self.state, ticket)
                self._record(record, 'marker_ready')
                self._offline()
                if (digest(self.launcher.read_bytes()) !=
                        signed['baseline_launcher_sha256'] or
                        digest(safe_path(self.resources / 'dashboard_beta14.html').read_bytes()) !=
                            signed['baseline_dashboard_sha256']):
                    raise Refused('manager_capability_baseline_changed')
                self._record(record, 'switch_pending')
                for name in APP_CODE_FILES:
                    path = self.resources / name
                    mode = (stat.S_IMODE(path.stat().st_mode) if path.exists()
                            else 0o600)
                    atomic_write(path, files['app/' + name], mode)
                self._record(record, 'switched')
                self._offline()
                self._verify_app(self.signer, self.app, folder)
                self._candidate_inventory(read_app_backup(folder), files)
                verify_staged(self.state, pinned_key=self.pin)
            except Exception as exc:
                if (folder / 'app-backup.json').is_file():
                    result = self._recover(self._pending())
                    result['reason'] = (str(exc) if isinstance(exc, Refused)
                                        else type(exc).__name__)
                    return result
                self._record(record, 'rolled_back')
                raise
            self._record(record, 'committed')
            self._finish(folder, record)
            return {'state': 'committed', 'installation_performed': True,
                    'backup_id': identifier, 'database_modified': False}
        finally:
            os.close(lock)
