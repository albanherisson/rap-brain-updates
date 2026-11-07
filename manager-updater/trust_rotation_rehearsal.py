"""Exercise the signed trust rotation against copies of the owner's app/code.

The only database and model configuration in this rehearsal are generated
synthetically. The live database and Ollama settings are never opened.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

from app_bundle_backup import inventory, restore_app_backup, save_app_backup
from creative_release import Refused
from creative_transaction import safe_path
from creative_trust_rotation import verify_rotation
from creative_trust_transaction import OfflineTrustRotation
from mac_offline_bootstrap_gate import verify_restored_app


def _copy_code(source, target):
    target.mkdir(mode=0o700)
    (target / 'data').mkdir(mode=0o700)
    for name in ('server.py', 'creative_engine.py'):
        shutil.copyfile(safe_path(source / name), target / name)
    (target / 'data' / 'ollama_model.json').write_text(
        json.dumps({'model': 'synthetic-test-only'}), encoding='utf-8')
    with sqlite3.connect(target / 'data' / 'rapbrain.sqlite3') as db:
        db.execute('CREATE TABLE synthetic_probe (value TEXT)')
        db.execute('INSERT INTO synthetic_probe VALUES (?)', ('retain',))


def rehearse_on_copy(source, launcher, state, signed_manifest):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    state = safe_path(state, directory=True)
    original_release = safe_path(launcher.parent / 'creative_release.py').read_bytes()
    signed, candidate = verify_rotation(signed_manifest, original_release)
    if signed['candidate_sha256'] != hashlib.sha256(candidate).hexdigest():
        raise Refused('rehearsal_candidate_changed')
    app = launcher.parents[2]
    original_inventory = inventory(app)
    offline = lambda *_: {'server_process_seen': False,
                          'manager_process_seen': False,
                          'port_8765_listening': False}
    with tempfile.TemporaryDirectory(prefix='trust-rehearsal-', dir=state) as temporary:
        root = Path(temporary).resolve(strict=True)
        copy_source = root / 'synthetic-rap-brain'
        _copy_code(source, copy_source)
        app_backup = root / 'app-source'
        app_backup.mkdir(mode=0o700)
        snapshot = save_app_backup(app, app_backup)
        if snapshot != original_inventory:
            raise Refused('rehearsal_source_app_changed')
        copy_app = app_backup / 'app-original.app'
        copy_launcher = copy_app / 'Contents' / 'Resources' / 'launch_manager.py'
        copy_state = root / 'copy-state'
        copy_state.mkdir(mode=0o700)
        transaction = OfflineTrustRotation(copy_source, copy_launcher, copy_state,
                                           inspector=offline)
        result = transaction.install(signed_manifest)
        if result.get('state') != 'committed':
            raise Refused('rehearsal_install_failed:' + result.get('reason', 'unknown'))
        if (copy_launcher.parent / 'creative_release.py').read_bytes() != candidate:
            raise Refused('rehearsal_candidate_changed')
        check = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                                str(copy_app)], capture_output=True, timeout=90)
        if check.returncode:
            raise Refused('rehearsal_candidate_signature_invalid')
        backup = copy_state / result['backup_id']
        if not restore_app_backup(copy_app, backup):
            raise Refused('rehearsal_restore_failed')
        if not verify_restored_app(copy_app, backup, copy_source, copy_launcher,
                                   inspector=offline):
            raise Refused('rehearsal_restored_signature_invalid')
        if inventory(copy_app) != original_inventory:
            raise Refused('rehearsal_not_identical')
        with sqlite3.connect(copy_source / 'data' / 'rapbrain.sqlite3') as db:
            if db.execute('SELECT value FROM synthetic_probe').fetchone() != ('retain',):
                raise Refused('rehearsal_synthetic_database_changed')
    return {'state': 'passed', 'active_files_modified': False,
            'live_sqlite_accessed': False, 'live_ollama_config_accessed': False}
