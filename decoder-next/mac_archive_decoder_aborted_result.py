#!/usr/bin/env python3
"""Preserve a proven aborted Decoder attempt so Beta 14 can start again.

Only moves its private UI receipt within secure-update. It does not touch the
server, app, database, library, analyses, Ollama settings or signed package.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ATTEMPT = '094627cae833484db19737aaa0ed3ae1'
BASELINE = 'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27'
CANDIDATE = 'b4d9f120ee5f2e1fedf4c1f73794bd4d3c3f4044bbd686d748b7cd3b94b89233'


def private_json(path, expected_limit=8192):
    if path.is_symlink() or not path.is_file():
        raise ValueError('private_record_missing')
    info = path.stat()
    if (info.st_uid != os.getuid() or info.st_mode & 0o077 or
            not 0 < info.st_size <= expected_limit):
        raise ValueError('private_record_unsafe')
    return json.loads(path.read_bytes())


def archive_checked(state, source, launcher, report, journal, accepted,
                    signed, package, *, verifier, archive_verifier,
                    baseline_verifier, inventory, signer, fsync):
    """Validate all safety evidence before moving one receipt within state."""
    if (report != {'attempt': ATTEMPT, 'installation_performed': None,
                   'reason': 'Refused', 'state': 'check_required'} or
            journal.get('id') != ATTEMPT or journal.get('phase') != 'aborted' or
            journal.get('schema') != 'rapbrain-manager-production-v1' or
            journal.get('sequence') != 4 or
            journal.get('source') != str(source) or
            journal.get('launcher') != str(launcher) or
            journal.get('server_baseline') != BASELINE or
            journal.get('baselines') != {'server.py': BASELINE} or
            accepted != {'sequence': 3}):
        raise ValueError('aborted_attempt_not_proven')
    for name in ('maintenance.ticket', 'bootstrap-intent.json',
                 'maintenance-intent.json'):
        if (state / name).exists() or (state / name).is_symlink():
            raise ValueError('maintenance_still_pending')
    manifest = verifier(signed)
    if (manifest['sequence'] != 4 or manifest['required_server_sha256'] != BASELINE or
            manifest['files'] != [{'path':'server.py',
                'baseline_sha256':BASELINE, 'payload_sha256':CANDIDATE}] or
            manifest['data_migrations'] != []):
        raise ValueError('signed_release_changed')
    archive_verifier(package, manifest)
    baseline_verifier(manifest, source, launcher.parent)
    inventory(launcher.parents[2])
    signer(launcher.parents[2])
    receipt_path = state / 'manager-handoff-result.json'
    saved = state / ('manager-handoff-result-check-required-' + ATTEMPT + '.json')
    if saved.exists() or saved.is_symlink() or private_json(receipt_path) != report:
        raise ValueError('receipt_archive_changed')
    os.rename(receipt_path, saved)
    try:
        fsync(state)
        if private_json(saved) != report or receipt_path.exists():
            raise ValueError('receipt_archive_not_verified')
    except Exception:
        if saved.exists() and not receipt_path.exists():
            os.rename(saved, receipt_path)
            fsync(state)
        raise
    return {'state':'archived', 'installation_performed':False,
            'active_code_modified':False, 'database_accessed':False}


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    home = Path.home()
    source = home / 'Downloads/rap-brain'
    app = home / 'Downloads/RapBrainManager_App_Beta14/Rap Brain Manager Beta 14.app'
    launcher = app / 'Contents/Resources/launch_manager.py'
    state = home / 'Downloads/RapBrainManagerBackups/secure-update'
    sys.path.insert(0, str(launcher.parent))
    from manager_helper_release import verify_staged
    helper = verify_staged(state)
    sys.path.insert(0, str(helper))
    from app_bundle_backup import inventory
    from creative_transaction import fsync_dir, safe_path
    from manager_update_helper import staged_release
    from manager_update_release import verify_archive, verify_baseline, verify_manifest
    from strict_json import parse_signed_json
    from worker_activity_gate import _state

    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    state = _state(state)
    report = private_json(state / 'manager-handoff-result.json')
    journal = private_json(state / 'manager-transaction.json')
    accepted = private_json(state / 'manager-accepted.json', 256)
    signed, package = staged_release(state, ATTEMPT)
    issued = parse_signed_json(signed)['signed_payload']['issued_at']

    def signer(target):
        result = subprocess.run(['/usr/bin/codesign', '--verify', '--deep',
            '--strict', str(target)], capture_output=True,
            stdin=subprocess.DEVNULL, timeout=90)
        if result.returncode:
            raise ValueError('app_signature_invalid')

    return archive_checked(state, source, launcher, report, journal, accepted,
        signed, package, verifier=lambda raw:verify_manifest(raw, now=issued),
        archive_verifier=verify_archive, baseline_verifier=verify_baseline,
        inventory=inventory, signer=signer, fsync=fsync_dir)


if __name__ == '__main__':
    try:
        print(json.dumps(main(), sort_keys=True))
    except Exception as exc:
        print('ARCHIVAGE REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
