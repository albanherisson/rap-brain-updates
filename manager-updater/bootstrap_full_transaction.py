"""Complete signed bootstrap transaction on an offline app/source pair.

No production offline lifecycle is supplied. The caller must prove the old
unguarded server and Beta 14 app fully stopped, retain exclusion during every
swap and restart, and re-sign the locally modified app before health succeeds.
This class refuses without that lifecycle; tests use disposable files only.
"""
import json
import os
from pathlib import Path
import stat

from bootstrap_full_release import FILES, PRIMARY, verify_full_bootstrap
from bootstrap_release import PUBLISHER_PIN
from bootstrap_transaction import BootstrapTransaction, TERMINAL
from creative_release import Refused, digest
from creative_transaction import Transaction, atomic_write, fsync_dir, safe_path
from strict_json import parse_signed_json


class FullBootstrapTransaction(BootstrapTransaction):
    def __init__(self, source, launcher, state, lifecycle=None, *, pinned_key=PUBLISHER_PIN):
        super().__init__(source, launcher, state, lifecycle, pinned_key=pinned_key)
        self.resources = self.launcher.parent
        self.paths = {'server.py': self.server, 'launch_manager.py': self.launcher,
                      'dashboard_beta14.html': self.resources / 'dashboard_beta14.html'}
        for name in FILES[3:]:
            self.paths[name] = self.resources / name

    def _baseline(self):
        if any(os.path.lexists(self.paths[name]) for name in FILES[3:]):
            raise Refused('bootstrap_runtime_already_present')
        return {name: safe_path(self.paths[name]).read_bytes() for name in PRIMARY}

    def _verify_saved_full(self, folder):
        originals = {name: safe_path(folder / ('before-' + name)).read_bytes()
                     for name in PRIMARY}
        raw = safe_path(folder / 'full-release.json').read_bytes()
        issued = parse_signed_json(raw)['signed_payload']['issued_at']
        manifest, files = verify_full_bootstrap(raw,
            safe_path(folder / 'full-release.zip').read_bytes(),
            *(originals[name] for name in PRIMARY), pinned_key=self.pin, now=issued)
        return manifest, files, originals

    def _backup_full(self, folder, raw, archive, originals):
        for name in PRIMARY:
            atomic_write(folder / ('before-' + name), originals[name])
        atomic_write(folder / 'full-release.json', raw)
        atomic_write(folder / 'full-release.zip', archive)
        Transaction(self.source, self.state, self.lifecycle).backup(
            folder, safe_path(self.source / 'creative_engine.py').read_bytes())
        fsync_dir(folder)

    def _assert_known_code(self, manifest, files, originals):
        for name in PRIMARY:
            current = digest(safe_path(self.paths[name]).read_bytes())
            if current not in (digest(originals[name]), digest(files[name])):
                raise Refused('bootstrap_unexpected_live_code_preserved')
        for name in FILES[3:]:
            path = self.paths[name]
            if os.path.lexists(path) and digest(safe_path(path).read_bytes()) != digest(files[name]):
                raise Refused('bootstrap_unexpected_live_runtime_preserved')

    def _replace_full(self, files, modes, lease):
        # Put the guarded server in place first. From this point an unrelated
        # fresh server launch sees the private ticket and refuses before DB
        # access. Recheck the offline proof after every replacement.
        lease.assert_stopped()
        atomic_write(self.server, files['server.py'], modes['server.py'])
        lease.assert_stopped()
        for name in FILES[3:]:
            if os.path.lexists(self.paths[name]):
                raise Refused('bootstrap_runtime_already_present')
            atomic_write(self.paths[name], files[name], 0o600)
            lease.assert_stopped()
        for name in PRIMARY[1:]:
            atomic_write(self.paths[name], files[name], modes[name])
            lease.assert_stopped()

    def _restore_full(self, originals, files, modes):
        for name in PRIMARY:
            atomic_write(self.paths[name], originals[name], modes[name])
        for name in FILES[3:]:
            path = self.paths[name]
            if os.path.lexists(path):
                if digest(safe_path(path).read_bytes()) != digest(files[name]):
                    raise Refused('bootstrap_unexpected_live_runtime_preserved')
                path.unlink()
        fsync_dir(self.resources)

    def _rollback_full(self, record, folder, lease):
        lease.stop_candidate()
        lease.assert_stopped()
        manifest, files, originals = self._verify_saved_full(folder)
        self._assert_known_code(manifest, files, originals)
        self.record(record, 'rollback_pending')
        self._restore_full(originals, files, record['modes'])
        if (any(digest(safe_path(self.paths[name]).read_bytes()) != digest(originals[name])
                for name in PRIMARY) or
                any(os.path.lexists(self.paths[name]) for name in FILES[3:])):
            raise Refused('bootstrap_rollback_integrity')
        if not lease.start_and_check():
            lease.stop_candidate()
            lease.assert_stopped()
            self.record(record, 'restored_stopped')
            return {'state': 'restored_stopped', 'installation_performed': False}
        self.record(record, 'rolled_back')
        return {'state': 'rolled_back', 'installation_performed': False}

    def _journal_full(self):
        record = self._read_journal()
        fields = {'id', 'source', 'launcher', 'modes', 'sequence', 'phase',
                  'baseline_server_sha256', 'baseline_launcher_sha256',
                  'baseline_dashboard_sha256', 'schema'}
        if (type(record) is not dict or record.keys() != fields or
                record['schema'] != 'rapbrain-guarded-bootstrap-v2' or
                record['source'] != str(self.source) or
                record['launcher'] != str(self.launcher) or
                type(record['id']) is not str or len(record['id']) != 32 or
                any(c not in '0123456789abcdef' for c in record['id']) or
                type(record['sequence']) is not int or record['sequence'] != 1 or
                type(record['modes']) is not dict or record['modes'].keys() != set(PRIMARY) or
                any(type(mode) is not int or not 0 <= mode <= 0o777
                    for mode in record['modes'].values()) or
                record['phase'] not in ('preparing', 'backup_ready', 'switch_pending',
                                        'switched', 'rollback_pending', *TERMINAL) or
                any(type(record.get('baseline_' + name + '_sha256')) is not str or
                    len(record['baseline_' + name + '_sha256']) != 64 or
                    any(c not in '0123456789abcdef'
                        for c in record['baseline_' + name + '_sha256'])
                    for name in ('server', 'launcher', 'dashboard'))):
            raise Refused('bootstrap_full_journal_invalid')
        return record

    def _assert_originals(self, record):
        names = ('server', 'launcher', 'dashboard')
        if (any(digest(safe_path(self.paths[path]).read_bytes()) !=
                record['baseline_' + name + '_sha256']
                for path, name in zip(PRIMARY, names)) or
                any(os.path.lexists(self.paths[name]) for name in FILES[3:])):
            raise Refused('bootstrap_baseline_changed_during_recovery')

    def recover_locked(self):
        if not os.path.lexists(self.journal):
            return None
        record = self._journal_full()
        if record['phase'] in TERMINAL:
            return None
        resume = getattr(self.lifecycle, 'resume_maintenance', None)
        if not callable(resume):
            raise Refused('bootstrap_original_attempt_required')
        folder = safe_path(self.state / record['id'], directory=True)
        with resume(self.source, self.launcher, record['id']) as lease:
            if lease.transaction_id != record['id']:
                raise Refused('bootstrap_attempt_changed')
            self._assert_excluded(lease)
            if record['phase'] in ('preparing', 'backup_ready'):
                if record['phase'] == 'backup_ready':
                    self._verify_saved_full(folder)
                self._assert_originals(record)
                phase = 'aborted' if lease.start_and_check() else 'restored_stopped'
                if phase == 'restored_stopped':
                    lease.stop_candidate()
                    lease.assert_stopped()
                self.record(record, phase)
                return {'state': phase, 'installation_performed': False}
            return self._rollback_full(record, folder, lease)

    def install(self, manifest_bytes, archive_bytes):
        with self.locked():
            recovered = self.recover_locked()
            if recovered:
                return recovered
            if any(os.path.lexists(self.state / name) for name in
                   ('bootstrap-intent.json', 'maintenance.ticket', 'maintenance-intent.json')):
                raise Refused('bootstrap_recovery_required')
            originals = self._baseline()
            manifest, files = verify_full_bootstrap(manifest_bytes, archive_bytes,
                *(originals[name] for name in PRIMARY), pinned_key=self.pin)
            with self.lifecycle.maintenance(self.source, self.launcher) as lease:
                self._assert_excluded(lease)
                if self._baseline() != originals:
                    raise Refused('bootstrap_baseline_changed')
                identifier = lease.transaction_id
                if (type(identifier) is not str or len(identifier) != 32 or
                        any(c not in '0123456789abcdef' for c in identifier)):
                    raise Refused('bootstrap_attempt_id_required')
                folder = self.state / identifier
                folder.mkdir(mode=0o700)
                fsync_dir(self.state)
                modes = {name: stat.S_IMODE(safe_path(self.paths[name]).stat().st_mode)
                         for name in PRIMARY}
                record = {'id': identifier, 'source': str(self.source),
                    'launcher': str(self.launcher), 'modes': modes,
                    'sequence': manifest['sequence'],
                    'schema': manifest['schema']}
                for name, path in zip(('server', 'launcher', 'dashboard'), PRIMARY):
                    record['baseline_' + name + '_sha256'] = digest(originals[path])
                self.record(record, 'preparing')
                try:
                    self._backup_full(folder, manifest_bytes, archive_bytes, originals)
                    self.record(record, 'backup_ready')
                    self._assert_excluded(lease)
                    self.record(record, 'switch_pending')
                    self._replace_full(files, modes, lease)
                    self.record(record, 'switched')
                    if not lease.start_and_check():
                        raise Refused('bootstrap_health_failed')
                except Exception:
                    if (folder / 'backup.json').exists() and (folder / 'full-release.json').exists():
                        return self._rollback_full(record, folder, lease)
                    self._assert_excluded(lease)
                    self._assert_originals(record)
                    phase = 'aborted' if lease.start_and_check() else 'restored_stopped'
                    if phase == 'restored_stopped':
                        lease.stop_candidate()
                        lease.assert_stopped()
                    self.record(record, phase)
                    raise
                if any(digest(safe_path(self.paths[name]).read_bytes()) != digest(files[name])
                       for name in FILES):
                    return self._rollback_full(record, folder, lease)
                self.record(record, 'committed')
                return {'state': 'committed', 'installation_performed': True,
                        'backup_id': identifier, 'database_replaced': False}
