"""Durable one-file update transaction; NOT wired to a real server yet.

A reviewed lifecycle adapter is mandatory. Its maintenance() context MUST
exclude all new jobs/launches, refuse busy/unknown processes, stop only a
verified owned idle process, and retain that exclusion through commit/rollback.
assert_stopped() must confirm exit of every writer. start_and_check() must
check authenticated application health and stop its owned candidate on failure.
stop_candidate() must stop only the exact process it started. A TCP-port probe
is NOT an acceptable implementation. No default adapter or live CLI exists.

The only active file ever replaced is creative_engine.py. Data backups are
never restored automatically over the live database, including after a crash.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import uuid

from creative_release import Refused, digest, verify_manifest, verify_archive, CREATIVE_KEY_PIN


def safe_path(path, *, directory=False):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise Refused('symlink_refused')
    if directory:
        if not path.is_dir():
            raise Refused('directory_missing')
    elif not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise Refused('regular_file_required')
    return path


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    safe_path(path.parent, directory=True)
    if path.is_symlink():
        raise Refused('symlink_destination')
    fd, name = tempfile.mkstemp(prefix='.rb-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fsync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path):
    return json.loads(safe_path(path).read_bytes())


class Transaction:
    def __init__(self, source, state, lifecycle=None, *, pinned_key=CREATIVE_KEY_PIN):
        self.source = safe_path(source, directory=True)
        self.state = Path(state).absolute()
        if (self.state == self.source or self.state.is_relative_to(self.source)
                or self.source.is_relative_to(self.state)):
            raise Refused('state_overlaps_source')
        for part in (self.state, *self.state.parents):
            if part.is_symlink():
                raise Refused('symlink_state')
        self.lifecycle = lifecycle
        self.pin = pinned_key
        self.target = self.source / 'creative_engine.py'
        self.journal = self.state / 'transaction.json'

    @contextmanager
    def locked(self):
        if self.lifecycle is None:
            raise Refused('reviewed_lifecycle_adapter_required')
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        safe_path(self.state, directory=True)
        if self.state.stat().st_uid != os.getuid() or self.state.stat().st_mode & 0o077:
            raise Refused('private_state_directory_required')
        fd = os.open(self.state / 'update.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def record(self, record, phase):
        record['phase'] = phase
        atomic_write(self.journal, json.dumps(record, sort_keys=True).encode())

    def assert_baseline(self, manifest):
        if digest(safe_path(self.target).read_bytes()) != manifest['baseline_sha256']:
            raise Refused('baseline_changed')
        if digest(safe_path(self.source / 'server.py').read_bytes()) != manifest['required_server_sha256']:
            raise Refused('server_changed')

    def backup(self, folder, original):
        """Same SQLite backup API as Beta14; config mandatory; restore drill mandatory."""
        db = safe_path(self.source / 'data' / 'rapbrain.sqlite3')
        config = safe_path(self.source / 'data' / 'ollama_model.json')
        if config.stat().st_size > 1024 * 1024:
            raise Refused('configuration_too_large')
        config_bytes = config.read_bytes()
        # Reject malformed config instead of silently omitting it.
        json.loads(config_bytes)
        atomic_write(folder / 'creative_engine.before.py', original)
        atomic_write(folder / 'ollama_model.json', config_bytes)
        target = folder / 'rapbrain.sqlite3'
        reader = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=12)
        writer = sqlite3.connect(target)
        try:
            reader.backup(writer, pages=128, sleep=0.1)
            if writer.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise Refused('backup_integrity')
        finally:
            writer.close()
            reader.close()
        with target.open('rb') as stream:
            os.fsync(stream.fileno())
        hashes = {name: digest((folder / name).read_bytes()) for name in
                  ('creative_engine.before.py', 'ollama_model.json', 'rapbrain.sqlite3')}
        with tempfile.TemporaryDirectory(prefix='restore-check-', dir=folder) as temporary:
            restored = Path(temporary)
            for name, expected in hashes.items():
                shutil.copyfile(folder / name, restored / name)
                if digest((restored / name).read_bytes()) != expected:
                    raise Refused('restore_not_identical')
            check = sqlite3.connect((restored / 'rapbrain.sqlite3').as_uri() + '?mode=ro', uri=True)
            try:
                if check.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise Refused('restore_integrity')
            finally:
                check.close()
        atomic_write(folder / 'backup.json', json.dumps({'hashes': hashes, 'restore_test': 'passed'}).encode())
        fsync_dir(folder)

    def rollback(self, record, folder, manifest, lease):
        lease.stop_candidate()
        lease.assert_stopped()
        original = safe_path(folder / 'creative_engine.before.py').read_bytes()
        if digest(original) != manifest['baseline_sha256']:
            raise Refused('rollback_backup_corrupt')
        current = digest(safe_path(self.target).read_bytes())
        if current not in (manifest['payload_sha256'], manifest['baseline_sha256']):
            raise Refused('unexpected_live_code_preserved')
        self.record(record, 'rollback_pending')
        atomic_write(self.target, original, record['mode'])
        if digest(self.target.read_bytes()) != manifest['baseline_sha256']:
            raise Refused('rollback_integrity')
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
        if record.get('source') != str(self.source):
            raise Refused('journal_source_mismatch')
        if record.get('phase') not in {'preparing', 'backup_ready', 'switch_pending', 'switched',
                                      'rollback_pending', 'committed', 'rolled_back', 'restored_stopped', 'aborted'}:
            raise Refused('unknown_journal_phase')
        if type(record.get('mode')) is not int or not 0 <= record['mode'] <= 0o777:
            raise Refused('invalid_saved_mode')
        if record['phase'] in ('committed', 'rolled_back', 'restored_stopped', 'aborted'):
            return None
        identifier = record['id']
        if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
            raise Refused('invalid_transaction_id')
        folder = safe_path(self.state / identifier, directory=True)
        raw = safe_path(folder / 'release.json').read_bytes()
        # Expired releases must still be recoverable; authenticate at issuance time.
        from strict_json import parse_signed_json
        issued = parse_signed_json(raw)['signed_payload']['issued_at']
        manifest = verify_manifest(raw, now=issued, pinned_key=self.pin)
        with self.lifecycle.maintenance(self.source) as lease:
            lease.assert_stopped()
            if record['phase'] in ('preparing', 'backup_ready'):
                self.assert_baseline(manifest)
                phase = 'aborted' if lease.start_and_check() else 'restored_stopped'
                if phase == 'restored_stopped':
                    lease.stop_candidate()
                    lease.assert_stopped()
                self.record(record, phase)
                return {'state': phase, 'installation_performed': False}
            return self.rollback(record, folder, manifest, lease)

    def recover(self):
        with self.locked():
            return self.recover_locked()

    def install(self, manifest_bytes, archive_bytes):
        with self.locked():
            recovered = self.recover_locked()
            if recovered:
                return recovered  # Recovery is never followed by a hidden second install.
            receipt = self.state / 'accepted.json'
            minimum = read_json(receipt)['sequence'] if receipt.exists() else 0
            # A crash between commit and receipt must not permit sequence replay.
            if self.journal.exists():
                previous = read_json(self.journal)
                if previous.get('source') != str(self.source):
                    raise Refused('journal_source_mismatch')
                if previous['phase'] == 'committed':
                    minimum = max(minimum, previous['sequence'])
                    # Repair a missing receipt BEFORE a later journal can supersede it.
                    atomic_write(receipt, json.dumps({'sequence': minimum}).encode())
            manifest = verify_manifest(manifest_bytes, minimum_sequence=minimum, pinned_key=self.pin)
            code = verify_archive(archive_bytes, manifest)
            self.assert_baseline(manifest)
            with self.lifecycle.maintenance(self.source) as lease:
                lease.assert_stopped()
                self.assert_baseline(manifest)
                original = self.target.read_bytes()
                mode = self.target.stat().st_mode & 0o777
                identifier = uuid.uuid4().hex
                folder = self.state / identifier
                folder.mkdir(mode=0o700)
                fsync_dir(self.state)
                atomic_write(folder / 'release.json', manifest_bytes)
                record = {'id': identifier, 'sequence': manifest['sequence'],
                          'mode': mode, 'source': str(self.source)}
                self.record(record, 'preparing')
                try:
                    self.backup(folder, original)
                    self.record(record, 'backup_ready')
                    lease.assert_stopped()
                    self.assert_baseline(manifest)
                    self.record(record, 'switch_pending')
                except Exception:
                    # Even a failed backup must not strand the previously idle app.
                    self.assert_baseline(manifest)
                    lease.assert_stopped()
                    phase = 'aborted' if lease.start_and_check() else 'restored_stopped'
                    if phase == 'restored_stopped':
                        lease.stop_candidate()
                        lease.assert_stopped()
                    self.record(record, phase)
                    raise
                try:
                    atomic_write(self.target, code, mode)
                    self.record(record, 'switched')
                    if digest(self.target.read_bytes()) != manifest['payload_sha256']:
                        raise Refused('installed_hash')
                    if not lease.start_and_check():
                        raise Refused('application_health_failed')
                except Exception:
                    return self.rollback(record, folder, manifest, lease)
                self.record(record, 'committed')
                atomic_write(receipt, json.dumps({'sequence': manifest['sequence']}).encode())
                return {'state': 'committed', 'installation_performed': True,
                        'backup_id': identifier, 'database_replaced': False}
