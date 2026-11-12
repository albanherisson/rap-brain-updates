"""Install and roll back the exact signed repair on isolated Mac copies."""
from pathlib import Path
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile

from app_bundle_backup import inventory, save_app_backup
from creative_release import Refused
from creative_transaction import safe_path
from manager_repair_transaction import OfflineManagerRepair


def smoke_copy(launcher, source, branch):
    # Reproduce the actual owner failure: the signed handoff committed and its
    # private receipt remains present when the Manager's isolated smoke starts.
    receipt_dir = branch / 'manager-backups' / 'secure-update'
    receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt = receipt_dir / 'manager-handoff-result.json'
    receipt.write_text(json.dumps({'attempt': 'f' * 32,
        'backup_id': 'f' * 32, 'installation_performed': True,
        'state': 'committed'}))
    receipt.chmod(0o600)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    if port in (8765, 11434):
        raise Refused('manager_repair_rehearsal_port_not_isolated')
    command = '''
from pathlib import Path
import sys
launcher, port = Path(sys.argv[1]), sys.argv[2]
namespace = {'__file__': str(launcher), '__name__': 'repair_smoke'}
exec(compile(launcher.read_bytes(), str(launcher), 'exec'), namespace)
namespace['CHILD'] = namespace['CHILD'].replace('8765', port)
sys.argv = [str(launcher), *sys.argv[3:]]
raise SystemExit(namespace['main']())
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', command, str(launcher), str(port),
        '--smoke-test', '--rap-brain-dir', str(source),
        '--backup-dir', str(branch / 'manager-backups')],
        capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
    if result.returncode != 0:
        raise Refused('manager_repair_rehearsal_runtime_failed')
    return True


def rehearse_on_copy(source, launcher, state, signed, archive, *, pinned_key=None,
                     signer=None, original_verifier=None,
                     restored_verifier=None, runtime_check=smoke_copy,
                     post_commit=None):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    state = safe_path(state, directory=True)
    app = launcher.parents[2]
    original = inventory(app)
    inspector = lambda *_: {'server_process_seen': False,
                            'manager_process_seen': False,
                            'port_8765_listening': False}
    with tempfile.TemporaryDirectory(prefix='manager-repair-rehearsal-') as temporary:
        root = Path(temporary).resolve()
        for scenario in ('commit', 'rollback'):
            branch = root / scenario
            branch.mkdir(mode=0o700)
            backup = branch / 'app-backup'
            backup.mkdir(mode=0o700)
            if save_app_backup(app, backup) != original:
                raise Refused('manager_repair_rehearsal_source_changed')
            copy_app = backup / 'app-original.app'
            copy_launcher = copy_app / 'Contents/Resources/launch_manager.py'
            copy_source = branch / 'rap-brain'
            data = copy_source / 'data'
            data.mkdir(parents=True, mode=0o700)
            (copy_source / 'server.py').write_bytes(safe_path(source / 'server.py').read_bytes())
            (copy_source / 'creative_engine.py').write_bytes(b'# synthetic-only\n')
            (data / 'ollama_model.json').write_text(json.dumps({'model': 'synthetic'}))
            with sqlite3.connect(data / 'rapbrain.sqlite3') as db:
                db.execute('CREATE TABLE analyses (id INTEGER PRIMARY KEY, text TEXT)')
                db.execute("INSERT INTO analyses(text) VALUES ('synthetic-only')")
            before_data = {p.name: p.read_bytes() for p in data.iterdir()}
            copy_state = branch / 'secure-update'
            copy_state.mkdir(mode=0o700)
            # The copy has its own helper, authenticated from the installed
            # original. Never use the live helper as the mutation target.
            old_helper = safe_path(state / 'helper', directory=True)
            copied_helper = copy_state / 'helper'
            copied_helper.mkdir(mode=0o700)
            for path in old_helper.iterdir():
                if path.is_symlink() or not path.is_file():
                    raise Refused('manager_repair_rehearsal_helper_unsafe')
                target = copied_helper / path.name
                target.write_bytes(path.read_bytes())
                target.chmod(0o600)
            opts = {'inspector': inspector}
            if pinned_key is not None:
                opts['pinned_key'] = pinned_key
            if signer is not None:
                opts['signer'] = signer
            if restored_verifier is not None:
                opts['restored_verifier'] = restored_verifier
            if original_verifier is not None:
                verifier = original_verifier
            else:
                from mac_offline_bootstrap_gate import verify_unchanged_app
                verifier = verify_unchanged_app
            calls = 0
            def verify_for_scenario(*args, **kwargs):
                nonlocal calls
                calls += 1
                # Initial app and signed candidate pass; only the installed
                # app in the rollback scenario is made to fail its health gate.
                if scenario == 'rollback' and calls == 3:
                    return False
                return verifier(*args, **kwargs)
            opts['original_verifier'] = verify_for_scenario
            result = OfflineManagerRepair(copy_source, copy_launcher, copy_state,
                                          **opts).install(signed, archive)
            expected = 'committed' if scenario == 'commit' else 'rolled_back'
            if result.get('state') != expected:
                # The transaction already rolled back the disposable copy.
                # Carry its bounded reason to the preparer without paths,
                # data, process details or exception traces.
                reason = result.get('reason', 'unknown')
                if type(reason) is not str or not reason.isascii() or not reason.replace('_', '').isalnum() or len(reason) > 80:
                    reason = 'unknown'
                raise Refused('manager_repair_rehearsal_' + scenario + '_' + reason)
            if scenario == 'rollback' and inventory(copy_app) != original:
                raise Refused('manager_repair_rehearsal_rollback_changed')
            if scenario == 'commit':
                if runtime_check(copy_launcher, copy_source, branch) is not True:
                    raise Refused('manager_repair_rehearsal_runtime_failed')
                if post_commit is not None and post_commit(copy_source,
                        copy_launcher, copy_state) is not True:
                    raise Refused('manager_repair_rehearsal_followup_failed')
            if before_data != {p.name: p.read_bytes() for p in data.iterdir()}:
                raise Refused('manager_repair_rehearsal_data_changed')
    if inventory(app) != original:
        raise Refused('manager_repair_rehearsal_active_app_changed')
    return {'state': 'passed', 'live_database_opened': False,
            'live_configuration_opened': False, 'active_files_modified': False}
