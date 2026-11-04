"""Rehearse the exact signed capability on a copied app and synthetic data."""
from pathlib import Path
import json
import sqlite3
import tempfile

from app_bundle_backup import inventory, save_app_backup
from creative_release import Refused
from creative_transaction import safe_path
from mac_offline_bootstrap_gate import verify_unchanged_app
from manager_capability_transaction import OfflineManagerCapability


def rehearse_on_copy(source, launcher, state, signed, archive, *,
                     pinned_key=None, signer=None, restored_verifier=None,
                     original_verifier=None):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    state = safe_path(state, directory=True)
    app = launcher.parents[2]
    original = inventory(app)
    inspector = lambda *_: {'server_process_seen': False,
                            'manager_process_seen': False,
                            'port_8765_listening': False}
    with tempfile.TemporaryDirectory(prefix='manager-capability-rehearsal-',
                                     dir=state) as temporary:
        root = Path(temporary).resolve()
        for scenario in ('commit', 'rollback'):
            branch = root / scenario
            branch.mkdir(mode=0o700)
            snapshot = branch / 'app-backup'
            snapshot.mkdir(mode=0o700)
            if save_app_backup(app, snapshot) != original:
                raise Refused('manager_capability_rehearsal_app_changed')
            copy_app = snapshot / 'app-original.app'
            copy_launcher = copy_app / 'Contents' / 'Resources' / 'launch_manager.py'
            copy_source = branch / 'rap-brain'
            data = copy_source / 'data'
            data.mkdir(parents=True, mode=0o700)
            for name in ('server.py', 'creative_engine.py'):
                (copy_source / name).write_bytes(safe_path(source / name).read_bytes())
            (data / 'ollama_model.json').write_text(json.dumps({
                'model': 'synthetic-rehearsal'}), encoding='utf-8')
            with sqlite3.connect(data / 'rapbrain.sqlite3') as db:
                db.execute('CREATE TABLE analyses (id INTEGER PRIMARY KEY, text TEXT)')
                db.execute("INSERT INTO analyses(text) VALUES ('synthetic-only')")
            before_data = {path.name: path.read_bytes() for path in data.iterdir()}
            copy_state = branch / 'secure-update'
            copy_state.mkdir(mode=0o700)
            options = {'inspector': inspector}
            if pinned_key is not None:
                options['pinned_key'] = pinned_key
            if signer is not None:
                options['signer'] = signer if scenario == 'commit' else lambda *_a, **_k: False
            elif scenario == 'rollback':
                options['signer'] = lambda *_a, **_k: False
            if restored_verifier is not None:
                options['restored_verifier'] = restored_verifier
            if original_verifier is not None:
                options['original_verifier'] = original_verifier
            result = OfflineManagerCapability(copy_source, copy_launcher,
                                              copy_state, **options).install(signed, archive)
            expected = 'committed' if scenario == 'commit' else 'rolled_back'
            if result.get('state') != expected:
                raise Refused('manager_capability_rehearsal_' + scenario + '_failed')
            if scenario == 'rollback' and inventory(copy_app) != original:
                raise Refused('manager_capability_rehearsal_rollback_changed')
            if scenario == 'commit':
                check = original_verifier or verify_unchanged_app
                if check(copy_app, copy_source, copy_launcher,
                         inspector=inspector) is not True:
                    raise Refused('manager_capability_rehearsal_signature')
            if before_data != {path.name: path.read_bytes() for path in data.iterdir()}:
                raise Refused('manager_capability_rehearsal_data_changed')
    if inventory(app) != original:
        raise Refused('manager_capability_rehearsal_live_app_changed')
    return {'state': 'passed', 'live_database_opened': False,
            'live_configuration_opened': False, 'active_files_modified': False}
