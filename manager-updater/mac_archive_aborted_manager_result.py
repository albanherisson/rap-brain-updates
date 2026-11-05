#!/usr/bin/env python3
"""Preserve the aborted receipt, then permit the unchanged Beta 14 to open.

The existing startup smoke gate incorrectly requires an idle result. This
one-time, fail-closed metadata move keeps the signed attempt's journal and
receipt for inspection. It never edits application code or Rap Brain data.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ATTEMPT = 'b8594a2a658747eda1b65e6265bf8d65'
BASELINE = 'e072f29f2416ed286c67f8faa73f517a1fb5deafb20cf125ac8f8417722a6464'


def private_json(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('private_record_missing')
    info = path.stat()
    if (info.st_uid != os.getuid() or info.st_mode & 0o077 or
            not 0 < info.st_size <= 8192):
        raise ValueError('private_record_unsafe')
    return json.loads(path.read_bytes())


def run():
    home = Path.home()
    source = home / 'Downloads' / 'rap-brain'
    app = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
           'Rap Brain Manager Beta 14.app')
    launcher = app / 'Contents' / 'Resources' / 'launch_manager.py'
    state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
    sys.path.insert(0, str(app / 'Contents' / 'Resources'))
    from manager_helper_release import verify_staged
    helper = verify_staged(state)
    sys.path.insert(0, str(helper))
    from creative_transaction import fsync_dir, safe_path
    from mac_offline_bootstrap_gate import assert_offline
    from manager_update_helper import staged_release
    from manager_update_release import verify_archive, verify_baseline, verify_manifest
    from strict_json import parse_signed_json
    from worker_activity_gate import _state

    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    state = _state(state)
    assert_offline(source, launcher)
    if any(os.path.lexists(state / name) for name in
           ('maintenance.ticket', 'bootstrap-intent.json',
            'maintenance-intent.json')):
        raise ValueError('maintenance_still_pending')
    journal = private_json(state / 'manager-transaction.json')
    receipt_path = state / 'manager-handoff-result.json'
    receipt = private_json(receipt_path)
    if (journal.get('id') != ATTEMPT or journal.get('phase') != 'aborted' or
            journal.get('source') != str(source) or
            journal.get('launcher') != str(launcher) or
            receipt.get('attempt') != ATTEMPT or receipt.get('state') != 'aborted' or
            receipt.get('installation_performed') is not False or
            hashlib.sha256(launcher.read_bytes()).hexdigest() != BASELINE):
        raise ValueError('aborted_attempt_not_proven')
    signed, archive = staged_release(state, ATTEMPT)
    issued = parse_signed_json(signed)['signed_payload']['issued_at']
    manifest = verify_manifest(signed, now=issued)
    files = verify_archive(archive, manifest)
    if set(files) != {'app/launch_manager.py'} or manifest['data_migrations'] != []:
        raise ValueError('signed_release_scope_changed')
    verify_baseline(manifest, source, launcher.parent)
    signature = subprocess.run(['/usr/bin/codesign', '--verify', '--deep',
        '--strict', str(app)], capture_output=True, stdin=subprocess.DEVNULL,
        timeout=90)
    if signature.returncode:
        raise ValueError('unchanged_app_signature_invalid')
    assert_offline(source, launcher)
    archive_path = state / ('manager-handoff-result-aborted-' + ATTEMPT + '.json')
    if os.path.lexists(archive_path) or private_json(receipt_path) != receipt:
        raise ValueError('receipt_archive_changed')
    os.rename(receipt_path, archive_path)
    fsync_dir(state)
    if private_json(archive_path) != receipt or receipt_path.exists():
        raise ValueError('receipt_archive_not_verified')
    print('Tentative abandonnee conservee ; Beta 14 peut redemarrer.', flush=True)


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print('CONTROLE REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
