"""External helper core for a Manager-initiated, signed update handoff.

No installed app invokes this yet. The production launcher must stage this
code outside the app bundle, then pass an inherited pipe and the original
parent start identity. This helper never stops an arbitrary process.
"""
import os
from pathlib import Path
import re
import argparse
import json
import sys

from creative_release import Refused
from creative_transaction import atomic_write, safe_path
from mac_offline_bootstrap_gate import assert_offline
from manager_handoff_proof import wait_for_parent_exit
from manager_offline_lifecycle import MacOfflineManagerLifecycle
from manager_update_release import MAX_ARCHIVE, verify_archive, verify_manifest
from manager_update_transaction import ManagerUpdateTransaction


IDENTIFIER = re.compile(r'[0-9a-f]{32}\Z')


def report_result(state, identifier, result):
    """Keep the outcome after the Manager HTTP process has exited."""
    if (type(identifier) is not str or not IDENTIFIER.fullmatch(identifier) or
            type(result) is not dict or
            result.get('state') not in ('committed', 'rolled_back', 'aborted',
                                        'restored_stopped', 'check_required')):
        raise Refused('manager_handoff_result_invalid')
    state = safe_path(state, directory=True)
    if state.stat().st_uid != os.getuid() or state.stat().st_mode & 0o077:
        raise Refused('manager_handoff_state_unsafe')
    report = {'attempt': identifier, 'state': result['state'],
              'installation_performed': (result['state'] == 'committed'
                  if result['state'] != 'check_required' else None)}
    if type(result.get('backup_id')) is str and result['backup_id'] == identifier:
        report['backup_id'] = identifier
    if type(result.get('reason')) is str:
        report['reason'] = result['reason'][:100]
    atomic_write(state / 'manager-handoff-result.json',
                 json.dumps(report, sort_keys=True).encode())
    return report


def staged_release(state, identifier):
    if type(identifier) is not str or not IDENTIFIER.fullmatch(identifier):
        raise Refused('manager_handoff_id_invalid')
    state = safe_path(state, directory=True)
    folder = safe_path(state / ('handoff-' + identifier), directory=True)
    if folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077:
        raise Refused('manager_handoff_stage_unsafe')
    values = []
    for name, limit in (('release.json', 65536), ('release.zip', MAX_ARCHIVE)):
        path = safe_path(folder / name)
        if (path.stat().st_uid != os.getuid() or
                path.stat().st_mode & 0o077 or
                not 0 < path.stat().st_size <= limit):
            raise Refused('manager_handoff_stage_unsafe')
        values.append(path.read_bytes())
    return tuple(values)


def run_handoff(source, launcher, state, identifier, read_fd, nonce_sha256,
                parent_pid, parent_start, *, waiter=wait_for_parent_exit,
                offline=assert_offline, lifecycle_factory=MacOfflineManagerLifecycle,
                transaction_factory=ManagerUpdateTransaction):
    waiter(read_fd, nonce_sha256, parent_pid, parent_start)
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    offline(source, launcher)
    signed, archive = staged_release(state, identifier)
    # Authenticate the original authorization even if a bad payload or an
    # expired publication requires aborting an otherwise idle handoff.
    from strict_json import parse_signed_json
    issued = parse_signed_json(signed)['signed_payload']['issued_at']
    verify_manifest(signed, now=issued)
    lifecycle = lifecycle_factory(source, launcher, state, signed,
                                  issued_recovery=True)
    transaction = transaction_factory(source, launcher, state, lifecycle)
    try:
        manifest = verify_manifest(signed)  # Freshness required for a new installation.
        verify_archive(archive, manifest)
        return transaction.install_handed_off(signed, archive, identifier)
    except Exception as exc:
        # Only the still-unchanged original may be restarted. If a journal is
        # pending or any code changed, abort_handoff_before_journal refuses.
        try:
            result = transaction.abort_handoff_before_journal(signed, identifier)
            return result | {'reason': type(exc).__name__}
        except Exception:
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='Rap Brain signed update handoff')
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--read-fd', required=True, type=int)
    parser.add_argument('--nonce-sha256', required=True)
    parser.add_argument('--parent-pid', required=True, type=int)
    parser.add_argument('--parent-start', required=True)
    args = parser.parse_args(argv)
    home = Path.home()
    source = home / 'Downloads' / 'rap-brain'
    launcher = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
        'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources' /
        'launch_manager.py')
    state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
    result = run_handoff(source, launcher, state, args.attempt, args.read_fd,
                         args.nonce_sha256, args.parent_pid, args.parent_start)
    report_result(state, args.attempt, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if result.get('state') == 'committed' else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        try:
            if len(sys.argv) > 1 and '--attempt' in sys.argv:
                identifier = sys.argv[sys.argv.index('--attempt') + 1]
                report_result(Path.home() / 'Downloads' / 'RapBrainManagerBackups' /
                    'secure-update', identifier,
                    {'state': 'check_required', 'reason': type(exc).__name__})
        except (IndexError, OSError, ValueError):
            pass
        print('INSTALLATION REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
