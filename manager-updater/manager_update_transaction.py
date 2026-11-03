"""Journaled Manager/server update, requiring an external reviewed lifecycle.

No default lifecycle is provided: a Manager cannot replace its own running
bundle. The lifecycle must authenticate an offline handoff, keep a maintenance
ticket through signing and health, and resume the same attempt after a crash.
"""
import json
import os
from pathlib import Path
import stat

from app_bundle_backup import read_app_backup, restore_app_backup, save_app_backup
from bootstrap_release import PUBLISHER_PIN
from bootstrap_transaction import BootstrapTransaction, TERMINAL
from creative_release import Refused, digest
from creative_transaction import Transaction, atomic_write, fsync_dir, read_json, safe_path
from manager_update_release import (verify_archive, verify_baseline,
                                    verify_manifest, ALLOWED)
from strict_json import parse_signed_json


class ManagerUpdateTransaction(BootstrapTransaction):
    def __init__(self, source, launcher, state, lifecycle=None, *,
                 pinned_key=PUBLISHER_PIN):
        super().__init__(source, launcher, state, lifecycle, pinned_key=pinned_key)
        if (self.launcher.parent.name != 'Resources' or
                self.launcher.parents[2].suffix != '.app'):
            raise Refused('manager_app_layout_unknown')
        self.app = self.launcher.parents[2]
        self.resources = self.launcher.parent
        self.journal = self.state / 'manager-transaction.json'
        self.receipt = self.state / 'manager-accepted.json'

    def _targets(self, manifest):
        return {entry['path']: (self.resources / entry['path'][4:]
                if entry['path'].startswith('app/') else self.source / entry['path'])
                for entry in manifest['files']}

    def _saved(self, folder):
        raw = safe_path(folder / 'manager-release.json').read_bytes()
        issued = parse_signed_json(raw)['signed_payload']['issued_at']
        manifest = verify_manifest(raw, pinned_key=self.pin, now=issued)
        files = verify_archive(safe_path(folder / 'manager-release.zip').read_bytes(),
                               manifest)
        snapshot = read_app_backup(folder)
        if digest(safe_path(folder / 'server.before.py').read_bytes()) != manifest['required_server_sha256']:
            raise Refused('manager_saved_server_baseline_changed')
        for entry in manifest['files']:
            name = entry['path']
            if name.startswith('app/'):
                original = snapshot.get('Contents/Resources/' + name[4:])
                if original is None or original['sha256'] != entry['baseline_sha256']:
                    raise Refused('manager_saved_app_baseline_changed')
            elif digest(safe_path(folder / 'server.before.py').read_bytes()) != entry['baseline_sha256']:
                raise Refused('manager_saved_server_baseline_changed')
        return manifest, files

    def _assert_known(self, manifest):
        for entry in manifest['files']:
            current = digest(safe_path(self._targets(manifest)[entry['path']]).read_bytes())
            if current not in (entry['baseline_sha256'], entry['payload_sha256']):
                raise Refused('manager_unexpected_live_code_preserved')

    def _baseline_record(self, record):
        if digest(safe_path(self.server).read_bytes()) != record['server_baseline']:
            raise Refused('manager_server_changed_during_recovery')
        for name, expected in record['baselines'].items():
            path = self.resources / name[4:] if name.startswith('app/') else self.source / name
            if digest(safe_path(path).read_bytes()) != expected:
                raise Refused('manager_baseline_changed_during_recovery')

    def _restore(self, record, folder, manifest, lease):
        lease.stop_candidate()
        self._assert_excluded(lease)
        saved_manifest, _ = self._saved(folder)
        if saved_manifest != manifest or saved_manifest['sequence'] != record['sequence']:
            raise Refused('manager_saved_attempt_changed')
        self._assert_known(manifest)
        saved_server = safe_path(folder / 'server.before.py').read_bytes()
        if digest(saved_server) != record['server_baseline']:
            raise Refused('manager_saved_server_changed')
        current_server = safe_path(self.server).read_bytes()
        if 'server.py' not in self._targets(manifest) and current_server != saved_server:
            raise Refused('manager_unselected_server_changed')
        self.record(record, 'rollback_pending')
        if 'server.py' in self._targets(manifest):
            atomic_write(self.server, saved_server, record['server_mode'])
        restore_app_backup(self.app, folder,
            allowed_extra=('Contents/_CodeSignature/CodeResources',))
        self._baseline_record(record)
        if not lease.start_and_check():
            lease.stop_candidate()
            self._assert_excluded(lease)
            self.record(record, 'restored_stopped')
            return {'state': 'restored_stopped', 'installation_performed': False}
        self.record(record, 'rolled_back')
        return {'state': 'rolled_back', 'installation_performed': False}

    def _journal_record(self):
        record = self._read_journal()
        if (type(record) is not dict or record.keys() !=
                {'id', 'source', 'launcher', 'phase', 'sequence', 'schema',
                 'baselines', 'server_mode', 'server_baseline'} or
                record['schema'] != 'rapbrain-manager-production-v1' or
                record['source'] != str(self.source) or
                record['launcher'] != str(self.launcher) or
                type(record['id']) is not str or len(record['id']) != 32 or
                any(c not in '0123456789abcdef' for c in record['id']) or
                type(record['sequence']) is not int or record['sequence'] < 1 or
                type(record['server_mode']) is not int or
                not 0 <= record['server_mode'] <= 0o777 or
                type(record['server_baseline']) is not str or
                len(record['server_baseline']) != 64 or
                any(c not in '0123456789abcdef' for c in record['server_baseline']) or
                type(record['baselines']) is not dict or
                not 0 < len(record['baselines']) <= len(ALLOWED) or
                any(type(name) is not str or
                    name not in ALLOWED or
                    type(value) is not str or len(value) != 64 or
                    any(c not in '0123456789abcdef' for c in value)
                    for name, value in record['baselines'].items()) or
                record['phase'] not in ('preparing', 'backup_ready',
                    'switch_pending', 'switched', 'rollback_pending', *TERMINAL)):
            raise Refused('manager_journal_invalid')
        return record

    def recover_locked(self):
        if not os.path.lexists(self.journal):
            return None
        record = self._journal_record()
        if record['phase'] in TERMINAL:
            return None
        resume = getattr(self.lifecycle, 'resume_maintenance', None)
        if not callable(resume):
            raise Refused('manager_original_attempt_required')
        folder = safe_path(self.state / record['id'], directory=True)
        with resume(self.source, self.launcher, record['id']) as lease:
            if lease.transaction_id != record['id']:
                raise Refused('manager_attempt_changed')
            self._assert_excluded(lease)
            if record['phase'] == 'preparing':
                self._baseline_record(record)
            else:
                manifest, _ = self._saved(folder)
                if ({entry['path']: entry['baseline_sha256'] for entry in manifest['files']}
                        != record['baselines'] or manifest['sequence'] != record['sequence']):
                    raise Refused('manager_saved_attempt_changed')
            if record['phase'] in ('preparing', 'backup_ready'):
                self._baseline_record(record)
                phase = 'aborted' if lease.start_and_check() else 'restored_stopped'
                if phase == 'restored_stopped':
                    lease.stop_candidate()
                    self._assert_excluded(lease)
                self.record(record, phase)
                return {'state': phase, 'installation_performed': False}
            return self._restore(record, folder, manifest, lease)

    def recover(self):
        with self.locked():
            return self.recover_locked()

    def install(self, signed_manifest, archive):
        with self.locked():
            recovered = self.recover_locked()
            if recovered is not None:
                return recovered
            for name, terminal in (
                    ('bootstrap-transaction.json', TERMINAL),
                    ('transaction.json', (*TERMINAL,)),
                    ('trust-rotation.json', ('committed', 'rolled_back'))):
                path = self.state / name
                if os.path.lexists(path):
                    prior = read_json(path)
                    if type(prior) is not dict or prior.get('phase') not in terminal:
                        raise Refused('manager_other_recovery_required')
            if any(os.path.lexists(self.state / name) for name in
                   ('bootstrap-intent.json', 'maintenance.ticket',
                    'maintenance-intent.json')):
                raise Refused('manager_previous_attempt_pending')
            minimum = 0
            if os.path.lexists(self.receipt):
                receipt = self._read_receipt()
                minimum = receipt['sequence']
            if os.path.lexists(self.journal):
                previous = self._journal_record()
                if previous['phase'] == 'committed':
                    minimum = max(minimum, previous['sequence'])
                    atomic_write(self.receipt, json.dumps({'sequence': minimum}).encode())
            manifest = verify_manifest(signed_manifest, minimum_sequence=minimum,
                                       pinned_key=self.pin)
            files = verify_archive(archive, manifest)
            verify_baseline(manifest, self.source, self.resources)
            with self.lifecycle.maintenance(self.source, self.launcher) as lease:
                return self._install_with_lease(lease, manifest, files, signed_manifest, archive)

    def _install_with_lease(self, lease, manifest, files, signed_manifest, archive):
        self._assert_excluded(lease)
        from creative_readiness import assert_no_pending_jobs
        assert_no_pending_jobs(self.source)
        targets = verify_baseline(manifest, self.source, self.resources)
        identifier = lease.transaction_id
        if (type(identifier) is not str or len(identifier) != 32 or
                any(c not in '0123456789abcdef' for c in identifier)):
            raise Refused('manager_attempt_id_required')
        folder = self.state / identifier
        folder.mkdir(mode=0o700)
        fsync_dir(self.state)
        record = {'id': identifier, 'source': str(self.source),
            'launcher': str(self.launcher), 'schema': manifest['schema'],
            'sequence': manifest['sequence'],
            'server_mode': stat.S_IMODE(safe_path(self.server).stat().st_mode),
            'server_baseline': digest(safe_path(self.server).read_bytes()),
            'baselines': {entry['path']: entry['baseline_sha256']
                          for entry in manifest['files']}}
        self.record(record, 'preparing')
        try:
            atomic_write(folder / 'server.before.py',
                         safe_path(self.server).read_bytes())
            atomic_write(folder / 'manager-release.json', signed_manifest)
            atomic_write(folder / 'manager-release.zip', archive)
            save_app_backup(self.app, folder)
            Transaction(self.source, self.state, self.lifecycle).backup(
                folder, safe_path(self.source / 'creative_engine.py').read_bytes())
            self._saved(folder)
            self.record(record, 'backup_ready')
            self._assert_excluded(lease)
            assert_no_pending_jobs(self.source)
            verify_baseline(manifest, self.source, self.resources)
            self.record(record, 'switch_pending')
            for entry in manifest['files']:
                name = entry['path']
                self._assert_excluded(lease)
                atomic_write(targets[name], files[name],
                    stat.S_IMODE(safe_path(targets[name]).stat().st_mode))
            self.record(record, 'switched')
            if not lease.start_and_check():
                raise Refused('manager_health_failed')
            if any(digest(safe_path(targets[entry['path']]).read_bytes()) !=
                    entry['payload_sha256'] for entry in manifest['files']):
                raise Refused('manager_installed_hash_changed')
        except Exception:
            if ((folder / 'app-backup.json').is_file() and
                    (folder / 'backup.json').is_file()):
                return self._restore(record, folder, manifest, lease)
            self._assert_excluded(lease)
            self._baseline_record(record)
            phase = 'aborted' if lease.start_and_check() else 'restored_stopped'
            if phase == 'restored_stopped':
                lease.stop_candidate()
                self._assert_excluded(lease)
            self.record(record, phase)
            raise
        self.record(record, 'committed')
        atomic_write(self.receipt,
                     json.dumps({'sequence': manifest['sequence']}).encode())
        return {'state': 'committed', 'installation_performed': True,
                'backup_id': identifier, 'database_replaced': False}

    def install_handed_off(self, signed_manifest, archive, identifier):
        """Resume an authenticated stopped handoff from the Manager parent.

        The parent must have stopped only its proven owned server, left the
        exact private ticket/intent in place, and exited. A separate helper
        proves that exit before calling this method. No new ticket is made.
        """
        with self.locked():
            if os.path.lexists(self.journal):
                previous = self._journal_record()
                if previous['phase'] not in TERMINAL:
                    if previous['id'] != identifier:
                        raise Refused('manager_other_attempt_pending')
                    folder = safe_path(self.state / identifier, directory=True)
                    saved = folder / 'manager-release.json'
                    if os.path.lexists(saved) and safe_path(saved).read_bytes() != signed_manifest:
                        raise Refused('manager_original_release_changed')
                    return self.recover_locked()
            if not (os.path.lexists(self.state / 'bootstrap-intent.json') and
                    os.path.lexists(self.state / 'maintenance.ticket')):
                raise Refused('manager_handoff_ticket_missing')
            if os.path.lexists(self.state / 'maintenance-intent.json'):
                raise Refused('manager_other_recovery_required')
            for name, terminal in (
                    ('bootstrap-transaction.json', TERMINAL),
                    ('transaction.json', TERMINAL),
                    ('trust-rotation.json', ('committed', 'rolled_back'))):
                path = self.state / name
                if os.path.lexists(path):
                    prior = read_json(path)
                    if type(prior) is not dict or prior.get('phase') not in terminal:
                        raise Refused('manager_other_recovery_required')
            minimum = self._read_receipt()['sequence'] if os.path.lexists(self.receipt) else 0
            if os.path.lexists(self.journal):
                previous = self._journal_record()
                if previous['phase'] == 'committed':
                    minimum = max(minimum, previous['sequence'])
                    atomic_write(self.receipt, json.dumps({'sequence': minimum}).encode())
            manifest = verify_manifest(signed_manifest, minimum_sequence=minimum,
                                       pinned_key=self.pin)
            files = verify_archive(archive, manifest)
            verify_baseline(manifest, self.source, self.resources)
            resume = getattr(self.lifecycle, 'resume_maintenance', None)
            if not callable(resume):
                raise Refused('manager_handoff_resume_required')
            with resume(self.source, self.launcher, identifier) as lease:
                if lease.transaction_id != identifier:
                    raise Refused('manager_handoff_attempt_changed')
                return self._install_with_lease(lease, manifest, files,
                                                signed_manifest, archive)

    def abort_handoff_before_journal(self, signed_manifest, identifier):
        """Restart unchanged old code after a verified, stopped pre-journal handoff.

        An unknown or partly switched state remains blocked for recovery. This
        method never restores data, writes application code, or signals a PID.
        """
        with self.locked():
            if os.path.lexists(self.journal):
                previous = self._journal_record()
                if previous['phase'] not in TERMINAL:
                    raise Refused('manager_journal_recovery_required')
                if previous['phase'] == 'committed':
                    minimum = (self._read_receipt()['sequence']
                               if os.path.lexists(self.receipt) else 0)
                    atomic_write(self.receipt, json.dumps({
                        'sequence': max(minimum, previous['sequence'])}).encode())
            from strict_json import parse_signed_json
            issued = parse_signed_json(signed_manifest)['signed_payload']['issued_at']
            manifest = verify_manifest(signed_manifest, pinned_key=self.pin, now=issued)
            verify_baseline(manifest, self.source, self.resources)
            resume = getattr(self.lifecycle, 'resume_maintenance', None)
            if not callable(resume):
                raise Refused('manager_handoff_resume_required')
            with resume(self.source, self.launcher, identifier) as lease:
                if lease.transaction_id != identifier:
                    raise Refused('manager_handoff_attempt_changed')
                self._assert_excluded(lease)
                verify_baseline(manifest, self.source, self.resources)
                from creative_readiness import assert_no_pending_jobs
                assert_no_pending_jobs(self.source)
                folder = self.state / identifier
                if not folder.exists():
                    folder.mkdir(mode=0o700)
                    fsync_dir(self.state)
                safe_path(folder, directory=True)
                if not lease.start_and_check():
                    lease.stop_candidate()
                    self._assert_excluded(lease)
                    raise Refused('manager_old_server_health_failed')
                record = {'id': identifier, 'source': str(self.source),
                    'launcher': str(self.launcher), 'schema': manifest['schema'],
                    'sequence': manifest['sequence'],
                    'server_mode': stat.S_IMODE(safe_path(self.server).stat().st_mode),
                    'server_baseline': manifest['required_server_sha256'],
                    'baselines': {entry['path']: entry['baseline_sha256']
                                  for entry in manifest['files']}}
                self.record(record, 'aborted')
                return {'state': 'aborted', 'installation_performed': False,
                        'database_replaced': False}
    def _read_receipt(self):
        path = safe_path(self.receipt)
        if (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077 or
                path.stat().st_size > 1024):
            raise Refused('manager_receipt_unsafe')
        data = json.loads(path.read_bytes())
        if (type(data) is not dict or data.keys() != {'sequence'} or
                type(data['sequence']) is not int or data['sequence'] < 1):
            raise Refused('manager_receipt_invalid')
        return data
