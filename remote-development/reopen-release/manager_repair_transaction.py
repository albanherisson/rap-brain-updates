"""Offline repair of the Manager app and its external helper, with rollback.

The owner must run this only from a separately signed Finder installer. It
refuses an active Manager or server. Rap Brain data is backed up and restore
tested, but is never a replacement target.
"""
import fcntl
import json
import os
from pathlib import Path
import secrets
import uuid

from app_bundle_backup import (_copy_verified, inventory, read_app_backup,
                               restore_app_backup, restore_xattrs, save_app_backup)
from creative_release import Refused, digest
from creative_transaction import Transaction, atomic_write, fsync_dir, safe_path
from mac_offline_bootstrap_gate import (assert_offline, resign_verified_app,
                                        verify_restored_app, verify_unchanged_app)
from manager_helper_inventory import HELPER_FILES
from manager_helper_release import verify_archive as verify_helper_archive
from manager_helper_release import verify_manifest as verify_helper_manifest
from manager_helper_release import verify_staged
from manager_repair_release import verify_release
from pending_attempt_recovery import _private_json
from strict_json import parse_signed_json
from worker_activity_gate import _lock, _state, begin_maintenance


PHASES = {'preparing', 'backup_ready', 'marker_ready', 'switch_pending',
          'switched', 'rollback_pending', 'committed', 'rolled_back'}
ALLOWED_APP = {'Contents/Resources/launch_manager.py',
               'Contents/MacOS/RapBrainManagerNative',
               'Contents/_CodeSignature/CodeResources'}


class OfflineManagerRepair:
    def __init__(self, source, launcher, state, *, inspector=None,
                 signer=resign_verified_app,
                 original_verifier=verify_unchanged_app,
                 restored_verifier=verify_restored_app, pinned_key=None):
        self.source = safe_path(source, directory=True)
        self.launcher = safe_path(launcher)
        self.resources = self.launcher.parent
        self.app = self.launcher.parents[2]
        if self.app.suffix != '.app' or self.resources.name != 'Resources':
            raise Refused('manager_repair_app_layout')
        self.state = _state(state)
        if (self.state.is_relative_to(self.source) or
                self.state.is_relative_to(self.app) or
                self.source.is_relative_to(self.state) or
                self.app.is_relative_to(self.state)):
            raise Refused('manager_repair_state_overlap')
        self.inspector = inspector
        self.signer = signer
        self.original_verifier = original_verifier
        self.restored_verifier = restored_verifier
        if pinned_key is None:
            from bootstrap_release import PUBLISHER_PIN
            pinned_key = PUBLISHER_PIN
        self.pin = pinned_key
        self.journal = self.state / 'manager-reopen-repair.json'

    def _offline(self):
        options = {'inspector': self.inspector} if self.inspector else {}
        return assert_offline(self.source, self.launcher, **options)

    def _app_check(self, check, *args):
        options = {'inspector': self.inspector} if self.inspector else {}
        if check(*args, self.source, self.launcher, **options) is not True:
            raise Refused('manager_repair_app_signature')

    def _write_record(self, record, phase):
        atomic_write(self.journal, json.dumps(record | {'phase': phase},
                                               sort_keys=True).encode())

    def _record(self):
        if not os.path.lexists(self.journal):
            return None
        record = _private_json(self.journal, 4096)
        if (type(record) is not dict or record.keys() !=
                {'id', 'source', 'launcher', 'release_sha256', 'archive_sha256',
                 'ticket_sha256', 'phase'} or record['phase'] not in PHASES or
                type(record['id']) is not str or len(record['id']) != 32 or
                any(c not in '0123456789abcdef' for c in record['id']) or
                record['source'] != str(self.source) or
                record['launcher'] != str(self.launcher) or
                any(type(record[k]) is not str or len(record[k]) != 64 or
                    any(c not in '0123456789abcdef' for c in record[k])
                    for k in ('release_sha256', 'archive_sha256',
                              'ticket_sha256'))):
            raise Refused('manager_repair_journal_invalid')
        return record

    def _saved(self, record):
        folder = safe_path(self.state / record['id'], directory=True)
        if folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077:
            raise Refused('manager_repair_backup_unsafe')
        raw = safe_path(folder / 'release.json').read_bytes()
        archive = safe_path(folder / 'repair.zip').read_bytes()
        if (digest(raw) != record['release_sha256'] or
                digest(archive) != record['archive_sha256']):
            raise Refused('manager_repair_saved_candidate_changed')
        issued = parse_signed_json(raw)['signed_payload']['issued_at']
        signed, files, helper_signed = verify_release(raw, archive,
                                                      pinned_key=self.pin, now=issued)
        return folder, signed, files, helper_signed

    def _ticket(self, record, folder):
        ticket = safe_path(folder / 'ticket').read_bytes()
        if (len(ticket) != 65 or ticket[-1:] != b'\n' or
                digest(ticket) != record['ticket_sha256']):
            raise Refused('manager_repair_ticket_changed')
        marker = self.state / 'maintenance.ticket'
        if os.path.lexists(marker) and safe_path(marker).read_bytes() != ticket:
            raise Refused('manager_repair_marker_changed')
        return ticket

    def _helper_snapshot(self, folder, signed_release):
        old = verify_staged(self.state, pinned_key=self.pin)
        signed = safe_path(old / 'signed-manifest.json').read_bytes()
        issued = parse_signed_json(signed)['signed_payload']['issued_at']
        manifest = verify_helper_manifest(signed, pinned_key=self.pin, now=issued)
        if (manifest['archive_sha256'] != signed_release['baseline_helper_sha256']
                or manifest['sequence'] >= signed_release['sequence']):
            raise Refused('manager_repair_helper_baseline_changed')
        saved = folder / 'helper-original'
        saved.mkdir(mode=0o700)
        for name in ('signed-manifest.json', *HELPER_FILES):
            data = safe_path(old / name).read_bytes()
            atomic_write(saved / name, data)
        self._check_helper_folder(saved, signed, manifest)
        return signed

    def _check_helper_folder(self, path, signed, manifest):
        path = safe_path(path, directory=True)
        if set(os.listdir(path)) != {'signed-manifest.json', *HELPER_FILES}:
            raise Refused('manager_repair_helper_layout')
        if safe_path(path / 'signed-manifest.json').read_bytes() != signed:
            raise Refused('manager_repair_helper_manifest_changed')
        for name in HELPER_FILES:
            if digest(safe_path(path / name).read_bytes()) != manifest['files'][name]:
                raise Refused('manager_repair_helper_changed')

    def _stage_helper(self, record, folder, helper_signed, archive):
        manifest = verify_helper_manifest(helper_signed, pinned_key=self.pin,
            now=parse_signed_json(helper_signed)['signed_payload']['issued_at'])
        members = verify_helper_archive(archive, manifest)
        staged = self.state / ('helper-next-' + record['id'])
        staged.mkdir(mode=0o700)
        atomic_write(staged / 'signed-manifest.json', helper_signed)
        for name in HELPER_FILES:
            atomic_write(staged / name, members[name])
        self._check_helper_folder(staged, helper_signed, manifest)
        fsync_dir(staged)

    def _candidate_app(self, folder, files):
        original = read_app_backup(folder)
        app = folder / 'app-candidate.app'
        _copy_verified(self.app, app, original)
        resources = app / 'Contents/Resources'
        atomic_write(resources / 'launch_manager.py', files['app/launch_manager.py'],
                     original['Contents/Resources/launch_manager.py']['mode'])
        launcher = resources / 'launch_manager.py'
        opts = {'inspector': self.inspector} if self.inspector else {}
        if self.signer(app, folder, self.source, launcher, **opts) is not True:
            raise Refused('manager_repair_candidate_signature')
        if self.original_verifier(app, self.source, launcher, **opts) is not True:
            raise Refused('manager_repair_candidate_verify')
        candidate = inventory(app)
        if (set(candidate) - set(original) - ALLOWED_APP or
                set(original) - set(candidate) or
                any(candidate[name] != original[name] for name in
                    set(candidate) & set(original) - ALLOWED_APP) or
                candidate['Contents/Resources/launch_manager.py']['sha256'] !=
                    digest(files['app/launch_manager.py']) or
                candidate['Contents/Resources/RapBrainManagerNative.swift']['sha256'] !=
                    digest(files['app/RapBrainManagerNative.swift'])):
            raise Refused('manager_repair_candidate_unexpected_change')
        atomic_write(folder / 'candidate-app.json',
                     json.dumps(candidate, sort_keys=True).encode())

    def _candidate_inventory(self, folder, files):
        path = safe_path(folder / 'candidate-app.json')
        if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise Refused('manager_repair_candidate_inventory_unsafe')
        candidate = _private_json(path, 1_500_000)
        if (type(candidate) is not dict or
                candidate != inventory(safe_path(folder / 'app-candidate.app', directory=True)) or
                candidate.get('Contents/Resources/launch_manager.py', {}).get('sha256') !=
                    digest(files['app/launch_manager.py']) or
                candidate.get('Contents/Resources/RapBrainManagerNative.swift', {}).get('sha256') !=
                    digest(files['app/RapBrainManagerNative.swift'])):
            raise Refused('manager_repair_candidate_inventory_changed')
        return candidate

    def _assert_app_known(self, folder, files):
        original = read_app_backup(folder)
        candidate = self._candidate_inventory(folder, files)
        current = inventory(self.app)
        if set(current) - set(original) - ALLOWED_APP or set(original) - set(current):
            raise Refused('manager_repair_unexpected_app_entry')
        for name in set(original) | set(current):
            if current.get(name) not in (original.get(name), candidate.get(name)):
                raise Refused('manager_repair_unknown_live_code')

    def _apply_candidate(self, folder, files):
        original = read_app_backup(folder)
        candidate = self._candidate_inventory(folder, files)
        app = safe_path(folder / 'app-candidate.app', directory=True)
        for name in sorted(ALLOWED_APP):
            entry = candidate.get(name)
            if entry is None:
                if name in original:
                    raise Refused('manager_repair_candidate_entry_missing')
                continue
            destination = self.app / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(destination, safe_path(app / name).read_bytes(), entry['mode'])
            restore_xattrs(destination, entry['xattrs'])
        if inventory(self.app) != candidate:
            raise Refused('manager_repair_live_candidate_changed')

    def _restore(self, record):
        folder, signed, files, helper_signed = self._saved(record)
        self._offline()
        self._ticket(record, folder)
        if record['phase'] in ('preparing', 'backup_ready'):
            if os.path.lexists(self.state / 'maintenance.ticket'):
                raise Refused('manager_repair_unexpected_marker')
            from manager_repair_release import LAUNCHER, NATIVE_SOURCE
            if (digest(self.launcher.read_bytes()) != LAUNCHER or
                    digest(safe_path(self.resources / 'RapBrainManagerNative.swift').read_bytes()) != NATIVE_SOURCE):
                raise Refused('manager_repair_unbacked_code_changed')
            self._app_check(self.original_verifier, self.app)
            original_helper = verify_staged(self.state, pinned_key=self.pin)
            old_signed = safe_path(original_helper / 'signed-manifest.json').read_bytes()
            old_manifest = verify_helper_manifest(old_signed, pinned_key=self.pin,
                now=parse_signed_json(old_signed)['signed_payload']['issued_at'])
            if old_manifest['archive_sha256'] != signed['baseline_helper_sha256']:
                raise Refused('manager_repair_unbacked_helper_changed')
            self._write_record(record, 'rolled_back')
            return {'state': 'rolled_back', 'installation_performed': False,
                    'database_modified': False}
        if not (folder / 'app-backup.json').exists():
            raise Refused('manager_repair_backup_missing')
        self._assert_app_known(folder, files)
        self._write_record(record, 'rollback_pending')
        restore_app_backup(self.app, folder,
            allowed_extra=('Contents/_CodeSignature/CodeResources',))
        self._app_check(self.restored_verifier, self.app, folder)
        old = self.state / ('helper-old-' + record['id'])
        candidate = self.state / ('helper-next-' + record['id'])
        target = self.state / 'helper'
        backup = safe_path(folder / 'helper-original', directory=True)
        old_signed = safe_path(backup / 'signed-manifest.json').read_bytes()
        issued = parse_signed_json(old_signed)['signed_payload']['issued_at']
        old_manifest = verify_helper_manifest(old_signed, pinned_key=self.pin, now=issued)
        self._check_helper_folder(backup, old_signed, old_manifest)
        if os.path.lexists(old):
            self._check_helper_folder(old, old_signed, old_manifest)
            if os.path.lexists(target):
                new_manifest = verify_helper_manifest(helper_signed, pinned_key=self.pin, now=signed['issued_at'])
                self._check_helper_folder(target, helper_signed, new_manifest)
                os.rename(target, candidate) if not os.path.lexists(candidate) else self._remove_known_helper(target)
            os.rename(old, target)
        else:
            self._check_helper_folder(target, old_signed, old_manifest)
        if os.path.lexists(candidate):
            new_manifest = verify_helper_manifest(helper_signed, pinned_key=self.pin, now=signed['issued_at'])
            self._check_helper_folder(candidate, helper_signed, new_manifest)
            self._remove_known_helper(candidate)
        verify_staged(self.state, pinned_key=self.pin)
        if inventory(self.app) != read_app_backup(folder):
            raise Refused('manager_repair_restore_changed')
        self._write_record(record, 'rolled_back')
        marker = self.state / 'maintenance.ticket'
        if os.path.lexists(marker):
            safe_path(marker).unlink()
            fsync_dir(self.state)
        return {'state': 'rolled_back', 'installation_performed': False,
                'database_modified': False}

    @staticmethod
    def _remove_known_helper(path):
        for name in ('signed-manifest.json', *HELPER_FILES):
            safe_path(path / name).unlink()
        path.rmdir()

    def install(self, raw=b'', archive=b''):
        self._offline()
        lock = _lock(self.state, 'update.lock', fcntl.LOCK_EX)
        try:
            self._offline()
            record = self._record()
            if record is not None:
                if record['phase'] == 'committed':
                    folder, signed, files, helper_signed = self._saved(record)
                    self._ticket(record, folder)
                    self._assert_app_known(folder, files)
                    if inventory(self.app) != self._candidate_inventory(folder, files):
                        raise Refused('manager_repair_committed_app_changed')
                    verify_staged(self.state, pinned_key=self.pin)
                    self._app_check(self.original_verifier, self.app)
                    marker = self.state / 'maintenance.ticket'
                    if os.path.lexists(marker):
                        safe_path(marker).unlink()
                        fsync_dir(self.state)
                    return {'state': 'committed', 'installation_performed': False,
                            'already_installed': True}
                if record['phase'] == 'rolled_back':
                    folder, signed, files, helper_signed = self._saved(record)
                    self._ticket(record, folder)
                    if (folder / 'app-backup.json').is_file():
                        if inventory(self.app) != read_app_backup(folder):
                            raise Refused('manager_repair_rollback_app_changed')
                    else:
                        from manager_repair_release import LAUNCHER, NATIVE_SOURCE
                        if (digest(self.launcher.read_bytes()) != LAUNCHER or
                                digest(safe_path(self.resources / 'RapBrainManagerNative.swift').read_bytes()) != NATIVE_SOURCE):
                            raise Refused('manager_repair_rollback_baseline_changed')
                    old = verify_staged(self.state, pinned_key=self.pin)
                    old_signed = safe_path(old / 'signed-manifest.json').read_bytes()
                    if verify_helper_manifest(old_signed, pinned_key=self.pin,
                            now=parse_signed_json(old_signed)['signed_payload']['issued_at'])['archive_sha256'] != signed['baseline_helper_sha256']:
                        raise Refused('manager_repair_rollback_helper_changed')
                    self._app_check(self.original_verifier, self.app)
                    marker = self.state / 'maintenance.ticket'
                    if os.path.lexists(marker):
                        if not (folder / 'app-backup.json').is_file():
                            raise Refused('manager_repair_unbacked_marker')
                        safe_path(marker).unlink()
                        fsync_dir(self.state)
                    return {'state': 'rolled_back', 'installation_performed': False}
                return self._restore(record)
            if any(os.path.lexists(self.state / name) for name in
                   ('maintenance.ticket', 'bootstrap-intent.json',
                    'maintenance-intent.json')):
                raise Refused('manager_repair_foreign_attempt')
            signed, files, helper_signed = verify_release(raw, archive,
                                                           pinned_key=self.pin)
            from manager_repair_release import LAUNCHER, NATIVE_SOURCE, SERVER
            if (digest(self.launcher.read_bytes()) != LAUNCHER or
                    digest(safe_path(self.resources / 'RapBrainManagerNative.swift').read_bytes()) != NATIVE_SOURCE or
                    digest(safe_path(self.source / 'server.py').read_bytes()) != SERVER):
                raise Refused('manager_repair_baseline_changed')
            self._app_check(self.original_verifier, self.app)
            identifier = uuid.uuid4().hex
            ticket = (secrets.token_hex(32) + '\n').encode()
            folder = self.state / identifier
            folder.mkdir(mode=0o700)
            atomic_write(folder / 'release.json', raw)
            atomic_write(folder / 'repair.zip', archive)
            atomic_write(folder / 'ticket', ticket)
            record = {'id': identifier, 'source': str(self.source),
                      'launcher': str(self.launcher),
                      'release_sha256': digest(raw),
                      'archive_sha256': digest(archive),
                      'ticket_sha256': digest(ticket)}
            self._write_record(record, 'preparing')
            try:
                self._offline()
                save_app_backup(self.app, folder)
                self._helper_snapshot(folder, signed)
                Transaction(self.source, self.state).backup(folder,
                    safe_path(self.source / 'creative_engine.py').read_bytes())
                self._write_record(record, 'backup_ready')
                self._stage_helper(record, folder, helper_signed, files['helper.zip'])
                self._candidate_app(folder, files)
                begin_maintenance(self.state, ticket)
                self._write_record(record, 'marker_ready')
                self._offline()
                self._assert_app_known(folder, files)
                self._write_record(record, 'switch_pending')
                old = self.state / ('helper-old-' + identifier)
                os.rename(self.state / 'helper', old)
                os.rename(self.state / ('helper-next-' + identifier), self.state / 'helper')
                fsync_dir(self.state)
                self._apply_candidate(folder, files)
                self._write_record(record, 'switched')
                self._offline()
                self._app_check(self.original_verifier, self.app)
                self._assert_app_known(folder, files)
                if inventory(self.app) != self._candidate_inventory(folder, files):
                    raise Refused('manager_repair_live_candidate_changed')
                verify_staged(self.state, pinned_key=self.pin)
            except Exception as exc:
                result = self._restore(self._record())
                result['reason'] = str(exc) if isinstance(exc, Refused) else type(exc).__name__
                return result
            self._write_record(record, 'committed')
            marker = self.state / 'maintenance.ticket'
            safe_path(marker).unlink()
            fsync_dir(self.state)
            return {'state': 'committed', 'installation_performed': True,
                    'backup_id': identifier, 'database_modified': False}
        finally:
            os.close(lock)
