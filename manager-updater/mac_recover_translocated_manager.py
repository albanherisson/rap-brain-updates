#!/usr/bin/env python3
"""One-time repair of an authenticated, pre-journal AppTranslocation handoff.

The original app path in bootstrap-intent.json vanished with the translocated
Finder instance. Bind that *same* stopped attempt to the signed app at its
stable Downloads path, then exec the already staged, signed recovery helper.
This does not install the update or open the live database itself.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


EXPECTED_LAUNCHER = 'e072f29f2416ed286c67f8faa73f517a1fb5deafb20cf125ac8f8417722a6464'
TRANSLOCATED = re.compile(
    r'/private/var/folders/[a-z0-9]+/[a-z0-9_]+/T/AppTranslocation/'
    r'[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}/d/'
    r'Rap Brain Manager Beta 14\.app/Contents/Resources/launch_manager\.py\Z')


def private_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            info.st_mode & 0o077):
        os.close(fd)
        raise ValueError('unsafe_existing_lock')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise
    return fd


def run():
    home = Path.home()
    source = home / 'Downloads' / 'rap-brain'
    app = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
           'Rap Brain Manager Beta 14.app')
    resources = app / 'Contents' / 'Resources'
    launcher = resources / 'launch_manager.py'
    state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
    sys.path.insert(0, str(resources))
    from manager_helper_release import verify_staged
    helper = verify_staged(state)
    sys.path.insert(0, str(helper))
    from creative_transaction import atomic_write, safe_path
    from mac_offline_bootstrap_gate import assert_offline
    from manager_update_helper import staged_release
    from manager_update_release import verify_archive, verify_baseline, verify_manifest
    from pending_attempt_recovery import _private_json
    from strict_json import parse_signed_json
    from worker_activity_gate import _state

    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    state = _state(state)
    assert_offline(source, launcher)
    if any(os.path.lexists(state / name) for name in
           ('manager-transaction.json', 'maintenance-intent.json')):
        raise ValueError('other_or_started_transaction')
    report = _private_json(state / 'manager-handoff-result.json', 4096)
    intent_path = state / 'bootstrap-intent.json'
    intent = _private_json(intent_path, 4096)
    if (type(report) is not dict or report.get('state') != 'check_required' or
            type(intent) is not dict or intent.keys() !=
            {'id', 'source', 'launcher', 'ticket_sha256'} or
            intent['id'] != report.get('attempt') or
            intent['source'] != str(source) or
            type(intent['launcher']) is not str or
            not TRANSLOCATED.fullmatch(intent['launcher']) or
            Path(intent['launcher']).exists() or
            type(intent['ticket_sha256']) is not str):
        raise ValueError('original_translocation_identity_unproven')
    marker = safe_path(state / 'maintenance.ticket')
    info = marker.stat()
    ticket = marker.read_bytes()
    if (info.st_uid != os.getuid() or info.st_mode & 0o077 or
            len(ticket) != 65 or ticket[-1:] != b'\n' or
            any(c not in b'0123456789abcdef' for c in ticket[:-1]) or
            hashlib.sha256(ticket).hexdigest() != intent['ticket_sha256']):
        raise ValueError('original_ticket_unproven')
    raw, archive = staged_release(state, intent['id'])
    issued = parse_signed_json(raw)['signed_payload']['issued_at']
    manifest = verify_manifest(raw, now=issued)
    files = verify_archive(archive, manifest)
    if (set(files) != {'app/launch_manager.py'} or
            manifest['data_migrations'] != [] or
            hashlib.sha256(launcher.read_bytes()).hexdigest() != EXPECTED_LAUNCHER):
        raise ValueError('release_or_app_scope_changed')
    verify_baseline(manifest, source, resources)
    verified = subprocess.run(['/usr/bin/codesign', '--verify', '--deep',
        '--strict', str(app)], stdin=subprocess.DEVNULL, capture_output=True,
        timeout=90)
    if verified.returncode:
        raise ValueError('original_app_signature_invalid')

    # Serialize the bridge against the transaction and guarded server.
    with os.fdopen(private_lock(state / 'transaction.lock'), 'rb', closefd=True):
        with os.fdopen(private_lock(state / 'update.lock'), 'rb', closefd=True):
            assert_offline(source, launcher)
            verify_baseline(manifest, source, resources)
            if _private_json(intent_path, 4096) != intent or marker.read_bytes() != ticket:
                raise ValueError('attempt_changed_during_bridge')
            backup = state / ('translocation-intent-' + intent['id'] + '.json')
            original = intent_path.read_bytes()
            if os.path.lexists(backup):
                if safe_path(backup).read_bytes() != original:
                    raise ValueError('original_intent_backup_changed')
            else:
                atomic_write(backup, original)
            updated = dict(intent, launcher=str(launcher))
            atomic_write(intent_path, json.dumps(updated, sort_keys=True).encode())
    print('Tentative rattachee au lanceur signe ; reprise en cours.', flush=True)
    recovery = helper / 'manager_update_recovery.py'
    os.execv(sys.executable, [sys.executable, '-B', str(recovery),
                             '--recover-existing'])


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print('REPRISE REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
