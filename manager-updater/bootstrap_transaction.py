"""Two-file guarded bootstrap transaction; no live lifecycle or UI entrypoint.

The mandatory lifecycle must prove the old unguarded server AND Beta 14 app
offline, keep a durable exclusion through restart, authenticate the exact
candidate, and resume the same attempt after a crash. No such production
lifecycle is supplied here. SQLite and Ollama config are backed up and checked
on a separate copy; neither is replaced during commit or rollback.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from bootstrap_release import PUBLISHER_PIN, verify_bootstrap
from creative_release import Refused, digest
from creative_transaction import Transaction, atomic_write, fsync_dir, read_json, safe_path
from strict_json import parse_signed_json


TERMINAL = ('committed', 'rolled_back', 'aborted', 'restored_stopped')


class BootstrapTransaction:
    def __init__(self, source, launcher, state, lifecycle=None, *, pinned_key=PUBLISHER_PIN):
        self.source = safe_path(source, directory=True)
        self.launcher = safe_path(launcher)
        self.state = Path(state).absolute()
        if (self.state == self.source or self.state.is_relative_to(self.source) or
                self.source.is_relative_to(self.state) or
                self.launcher.is_relative_to(self.state) or
                self.state.is_relative_to(self.launcher.parent)):
            raise Refused('bootstrap_state_overlap')
        for part in (self.state, *self.state.parents):
            if part.is_symlink():
                raise Refused('bootstrap_state_symlink')
        self.server = self.source / 'server.py'
        self.lifecycle = lifecycle
        self.pin = pinned_key
        self.journal = self.state / 'bootstrap-transaction.json'

    @contextmanager
    def locked(self):
        if self.lifecycle is None:
            raise Refused('bootstrap_offline_lifecycle_required')
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        safe_path(self.state, directory=True)
        info = self.state.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Refused('bootstrap_private_state_required')
        fd = os.open(self.state / 'bootstrap.lock',
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def record(self, record, phase):
        record['phase'] = phase
        atomic_write(self.journal, json.dumps(record, sort_keys=True).encode())

    def _assert_excluded(self, lease):
        lease.assert_stopped()
        ticket = getattr(lease, 'ticket', None)
        if (type(ticket) is not bytes or len(ticket) != 65 or
                ticket[-1:] != b'\n' or
                any(c not in b'0123456789abcdef' for c in ticket[:-1])):
            raise Refused('bootstrap_ticket_required')
        marker = safe_path(self.state / 'maintenance.ticket')
        intent = safe_path(self.state / 'bootstrap-intent.json')
        if (marker.stat().st_uid != os.getuid() or
                intent.stat().st_uid != os.getuid() or
                marker.stat().st_mode & 0o077 or intent.stat().st_mode & 0o077 or
                marker.read_bytes() != ticket):
            raise Refused('bootstrap_exclusion_changed')
        raw = intent.read_bytes()
        if len(raw) > 4096:
            raise Refused('bootstrap_intent_oversize')
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise Refused('bootstrap_intent_invalid') from exc
        if (type(record) is not dict or record.keys() !=
                {'id', 'source', 'launcher', 'ticket_sha256'} or
                record['id'] != lease.transaction_id or
                record['source'] != str(self.source) or
                record['launcher'] != str(self.launcher) or
                record['ticket_sha256'] != hashlib.sha256(ticket).hexdigest()):
            raise Refused('bootstrap_exclusion_changed')

    def _backup(self, folder, manifest_bytes, archive_bytes, originals):
        # Reuse the already-tested SQLite/config backup and separate restore
        # drill from the signed one-file transaction.
        atomic_write(folder / 'server.before.py', originals['server.py'])
        atomic_write(folder / 'launcher.before.py', originals['launch_manager.py'])
        atomic_write(folder / 'bootstrap-release.json', manifest_bytes)
        atomic_write(folder / 'bootstrap.zip', archive_bytes)
        helper = Transaction(self.source, self.state, self.lifecycle)
        helper.backup(folder, safe_path(self.source / 'creative_engine.py').read_bytes())
        fsync_dir(folder)

    def _originals(self, folder):
        return {'server.py': safe_path(folder / 'server.before.py').read_bytes(),
                'launch_manager.py': safe_path(folder / 'launcher.before.py').read_bytes()}

    def _verify_saved(self, folder):
        raw = safe_path(folder / 'bootstrap-release.json').read_bytes()
        issued = parse_signed_json(raw)['signed_payload']['issued_at']
        originals = self._originals(folder)
        manifest, files = verify_bootstrap(raw,
            safe_path(folder / 'bootstrap.zip').read_bytes(),
            originals['server.py'], originals['launch_manager.py'],
            pinned_key=self.pin, now=issued)
        return manifest, files, originals

    def _replace(self, files, modes):
        atomic_write(self.server, files['server.py'], modes['server.py'])
        atomic_write(self.launcher, files['launch_manager.py'], modes['launch_manager.py'])

    def _rollback(self, record, folder, lease):
        lease.stop_candidate()
        lease.assert_stopped()
        manifest, files, originals = self._verify_saved(folder)
        for path, name, baseline, candidate in (
                (self.server, 'server.py', manifest['baseline_server_sha256'],
                 manifest['candidate_server_sha256']),
                (self.launcher, 'launch_manager.py', manifest['baseline_launcher_sha256'],
                 manifest['candidate_launcher_sha256'])):
            if digest(safe_path(path).read_bytes()) not in (baseline, candidate):
                raise Refused('bootstrap_unexpected_live_code_preserved')
        self.record(record, 'rollback_pending')
        self._replace(originals, record['modes'])
        if (digest(self.server.read_bytes()) != manifest['baseline_server_sha256'] or
                digest(self.launcher.read_bytes()) != manifest['baseline_launcher_sha256']):
            raise Refused('bootstrap_rollback_integrity')
        if not lease.start_and_check():
            lease.stop_candidate()
            lease.assert_stopped()
            self.record(record, 'restored_stopped')
            return {'state': 'restored_stopped', 'installation_performed': False}
        self.record(record, 'rolled_back')
        return {'state': 'rolled_back', 'installation_performed': False}

    def recover_locked(self):
        if not self.journal.exists():
            return None
        record = read_json(self.journal)
        if (type(record) is not dict or record.get('source') != str(self.source) or
                record.get('launcher') != str(self.launcher)):
            raise Refused('bootstrap_journal_identity_changed')
        if record.get('phase') in TERMINAL:
            return None
        if (record.get('phase') not in
                ('preparing', 'backup_ready', 'server_pending', 'server_switched',
                 'launcher_pending', 'both_switched', 'rollback_pending') or
                type(record.get('id')) is not str or len(record['id']) != 32 or
                any(c not in '0123456789abcdef' for c in record['id']) or
                type(record.get('modes')) is not dict or
                record['modes'].keys() != {'server.py', 'launch_manager.py'} or
                any(type(mode) is not int or not 0 <= mode <= 0o777
                    for mode in record['modes'].values())):
            raise Refused('bootstrap_journal_invalid')
        resume = getattr(self.lifecycle, 'resume_maintenance', None)
        if not callable(resume):
            raise Refused('bootstrap_original_attempt_required')
        folder = safe_path(self.state / record['id'], directory=True)
        with resume(self.source, self.launcher, record['id']) as lease:
            if getattr(lease, 'transaction_id', None) != record['id']:
                raise Refused('bootstrap_attempt_changed')
            self._assert_excluded(lease)
            if record['phase'] in ('preparing', 'backup_ready'):
                manifest, _, originals = self._verify_saved(folder)
                if (digest(safe_path(self.server).read_bytes()) !=
                        manifest['baseline_server_sha256'] or
                        digest(safe_path(self.launcher).read_bytes()) !=
                        manifest['baseline_launcher_sha256']):
                    raise Refused('bootstrap_baseline_changed_during_recovery')
                phase = 'aborted' if lease.start_and_check() else 'restored_stopped'
                if phase == 'restored_stopped':
                    lease.stop_candidate()
                    lease.assert_stopped()
                self.record(record, phase)
                return {'state': phase, 'installation_performed': False}
            return self._rollback(record, folder, lease)

    def recover(self):
        with self.locked():
            return self.recover_locked()

    def install(self, manifest_bytes, archive_bytes):
        with self.locked():
            result = self.recover_locked()
            if result:
                return result
            if (os.path.lexists(self.state / 'bootstrap-intent.json') or
                    os.path.lexists(self.state / 'maintenance.ticket') or
                    os.path.lexists(self.state / 'maintenance-intent.json')):
                raise Refused('bootstrap_recovery_required')
            originals = {'server.py': safe_path(self.server).read_bytes(),
                         'launch_manager.py': safe_path(self.launcher).read_bytes()}
            manifest, files = verify_bootstrap(manifest_bytes, archive_bytes,
                originals['server.py'], originals['launch_manager.py'], pinned_key=self.pin)
            with self.lifecycle.maintenance(self.source, self.launcher) as lease:
                self._assert_excluded(lease)
                if (self.server.read_bytes() != originals['server.py'] or
                        self.launcher.read_bytes() != originals['launch_manager.py']):
                    raise Refused('bootstrap_baseline_changed')
                identifier = getattr(lease, 'transaction_id', None)
                if (type(identifier) is not str or len(identifier) != 32 or
                        any(c not in '0123456789abcdef' for c in identifier)):
                    raise Refused('bootstrap_attempt_id_required')
                folder = self.state / identifier
                folder.mkdir(mode=0o700)
                fsync_dir(self.state)
                modes = {name: stat.S_IMODE(safe_path(path).stat().st_mode) for name, path in
                         (('server.py', self.server), ('launch_manager.py', self.launcher))}
                record = {'id': identifier, 'source': str(self.source),
                          'launcher': str(self.launcher), 'modes': modes,
                          'sequence': manifest['sequence']}
                self.record(record, 'preparing')
                try:
                    self._backup(folder, manifest_bytes, archive_bytes, originals)
                    self.record(record, 'backup_ready')
                    self._assert_excluded(lease)
                    self.record(record, 'server_pending')
                    atomic_write(self.server, files['server.py'], modes['server.py'])
                    self.record(record, 'server_switched')
                    self._assert_excluded(lease)
                    self.record(record, 'launcher_pending')
                    atomic_write(self.launcher, files['launch_manager.py'], modes['launch_manager.py'])
                    self.record(record, 'both_switched')
                    if not lease.start_and_check():
                        raise Refused('bootstrap_health_failed')
                except Exception:
                    # If backup is incomplete, recovery must remain fail-closed
                    # instead of restoring from an unverified partial folder.
                    if ((folder / 'backup.json').exists() and
                            (folder / 'bootstrap-release.json').exists()):
                        return self._rollback(record, folder, lease)
                    self._assert_excluded(lease)
                    if (self.server.read_bytes() != originals['server.py'] or
                            self.launcher.read_bytes() != originals['launch_manager.py']):
                        raise Refused('bootstrap_partial_backup_and_changed_code')
                    phase = 'aborted' if lease.start_and_check() else 'restored_stopped'
                    if phase == 'restored_stopped':
                        lease.stop_candidate()
                        lease.assert_stopped()
                    self.record(record, phase)
                    raise
                if (digest(self.server.read_bytes()) != manifest['candidate_server_sha256'] or
                        digest(self.launcher.read_bytes()) != manifest['candidate_launcher_sha256']):
                    return self._rollback(record, folder, lease)
                self.record(record, 'committed')
                return {'state': 'committed', 'installation_performed': True,
                        'backup_id': identifier, 'database_replaced': False}
