"""Durable pre-journal maintenance intent for disposable transaction drills.

No live entrypoint. A future lifecycle adapter must serialize this with its
transaction lock and authenticate the owned process before creating the marker.
Recovery never restores SQLite or modifies application code.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from creative_release import Refused
from creative_transaction import atomic_write, safe_path, fsync_dir
from worker_activity_gate import _state, _lock, begin_maintenance


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def journal_digest(state, source):
    path = state / 'transaction.json'
    if not path.exists():
        if path.is_symlink():
            raise Refused('unsafe_previous_journal')
        return None
    journal = safe_path(path)
    if journal.stat().st_uid != os.getuid() or journal.stat().st_mode & 0o077:
        raise Refused('unsafe_previous_journal')
    raw = journal.read_bytes()
    if len(raw) > 65536:
        raise Refused('previous_journal_too_large')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Refused('previous_journal_duplicate_field')
            result[key] = value
        return result

    try:
        record = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise Refused('previous_journal_invalid') from exc
    if (type(record) is not dict or
            record.get('phase') not in ('committed', 'rolled_back', 'aborted') or
            record.get('source') != str(source)):
        raise Refused('previous_transaction_pending')
    return sha(raw)


def begin_attempt(state, source, ticket, attempt_id):
    state = _state(state)
    source = safe_path(source, directory=True)
    if (type(attempt_id) is not str or len(attempt_id) != 32 or
            any(c not in '0123456789abcdef' for c in attempt_id) or
            type(ticket) is not bytes or len(ticket) != 65 or
            ticket[-1:] != b'\n' or
            any(c not in b'0123456789abcdef' for c in ticket[:-1])):
        raise Refused('invalid_attempt_identity')
    intent = state / 'maintenance-intent.json'
    if os.path.lexists(intent) or os.path.lexists(state / 'maintenance.ticket'):
        raise Refused('existing_maintenance_attempt')
    record = {'schema': 'rapbrain-prejournal-intent-v1', 'id': attempt_id,
              'source': str(source), 'ticket_sha256': sha(ticket),
              'engine_sha256': sha(safe_path(source / 'creative_engine.py').read_bytes()),
              'server_sha256': sha(safe_path(source / 'server.py').read_bytes()),
              'previous_journal_sha256': journal_digest(state, source)}
    atomic_write(intent, json.dumps(record, sort_keys=True).encode())
    try:
        begin_maintenance(state, ticket)
    except BaseException:
        # A busy request/job may refuse before marker creation. Retain an
        # intent if a partial marker exists, so recovery stays fail-closed.
        if not os.path.lexists(state / 'maintenance.ticket'):
            os.unlink(intent)
            fsync_dir(state)
        raise
    return attempt_id


def recover_unjournaled(state, source, ticket, attempt_id):
    """Release only an unchanged, uniquely identified pre-journal attempt."""
    state = _state(state)
    source = safe_path(source, directory=True)
    raw = safe_path(state / 'maintenance-intent.json').read_bytes()
    if len(raw) > 4096:
        raise Refused('intent_oversize')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Refused('intent_duplicate_field')
            result[key] = value
        return result

    try:
        record = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise Refused('intent_invalid') from exc
    if (type(record) is not dict or
            record.keys() != {'schema', 'id', 'source', 'ticket_sha256',
                              'engine_sha256', 'server_sha256', 'previous_journal_sha256'} or
            record['schema'] != 'rapbrain-prejournal-intent-v1' or
            record['id'] != attempt_id or record['source'] != str(source) or
            type(ticket) is not bytes or record['ticket_sha256'] != sha(ticket) or
            record['previous_journal_sha256'] != journal_digest(state, source) or
            record['engine_sha256'] != sha(safe_path(source / 'creative_engine.py').read_bytes()) or
            record['server_sha256'] != sha(safe_path(source / 'server.py').read_bytes())):
        raise Refused('prejournal_baseline_changed')
    # The guarded parent and worker both retain update.lock shared. An
    # exclusive lock proves neither is still alive before clearing the marker.
    lifetime_fd = os.open(state / 'update.lock', os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(lifetime_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077):
            raise Refused('unsafe_lifetime_lock')
        try:
            fcntl.flock(lifetime_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refused('server_still_running') from exc
        admission_fd = _lock(state, 'admission.lock', fcntl.LOCK_EX)
        try:
            job_fd = _lock(state, 'worker-job.lock', fcntl.LOCK_EX)
            try:
                marker_fd = os.open(state / 'maintenance.ticket', os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    marker = os.fstat(marker_fd)
                    if (not stat.S_ISREG(marker.st_mode) or marker.st_uid != os.getuid() or
                            marker.st_mode & 0o077 or os.read(marker_fd, 66) != ticket):
                        raise Refused('prejournal_ticket_changed')
                finally:
                    os.close(marker_fd)
                # Recheck after acquiring all locks; a new journal phase must
                # never be mistaken for the pre-journal window.
                if (record['previous_journal_sha256'] != journal_digest(state, source) or
                        record['engine_sha256'] != sha(safe_path(source / 'creative_engine.py').read_bytes()) or
                        record['server_sha256'] != sha(safe_path(source / 'server.py').read_bytes())):
                    raise Refused('prejournal_state_changed')
                os.unlink(state / 'maintenance.ticket')
                os.unlink(state / 'maintenance-intent.json')
                fsync_dir(state)
            finally:
                os.close(job_fd)
        finally:
            os.close(admission_fd)
    finally:
        os.close(lifetime_fd)
    return {'state': 'prejournal_recovered', 'code_modified': False,
            'database_modified': False}
