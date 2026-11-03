"""Resume one authenticated, already stopped Manager update attempt.

This external entrypoint is not installed. It never fetches GitHub, stops a
process, opens the live database directly, or allocates a new maintenance
ticket. The original signed stage and private intent must still be present.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from creative_release import Refused
from creative_transaction import safe_path
from mac_offline_bootstrap_gate import assert_offline
from manager_offline_lifecycle import MacOfflineManagerLifecycle
from manager_update_helper import report_result, staged_release
from manager_update_release import verify_manifest
from manager_update_transaction import ManagerUpdateTransaction, TERMINAL
from pending_attempt_recovery import _private_json
from strict_json import parse_signed_json
from worker_activity_gate import _state


IDENTIFIER = re.compile(r'[0-9a-f]{32}\Z')


def recover_existing(source, launcher, state, *, offline=assert_offline,
                     lifecycle_factory=MacOfflineManagerLifecycle,
                     transaction_factory=ManagerUpdateTransaction,
                     manifest_verifier=verify_manifest):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    state = _state(state)
    offline(source, launcher)
    intent = _private_json(state / 'bootstrap-intent.json', 4096)
    if (type(intent) is not dict or intent.keys() !=
            {'id', 'source', 'launcher', 'ticket_sha256'} or
            type(intent['id']) is not str or not IDENTIFIER.fullmatch(intent['id']) or
            intent['source'] != str(source) or
            intent['launcher'] != str(launcher)):
        raise Refused('manager_recovery_intent_invalid')
    identifier = intent['id']
    if not os.path.lexists(state / 'maintenance.ticket'):
        raise Refused('manager_recovery_ticket_missing')
    signed, _archive = staged_release(state, identifier)
    issued = parse_signed_json(signed)['signed_payload']['issued_at']
    manifest_verifier(signed, now=issued)
    lifecycle = lifecycle_factory(source, launcher, state, signed,
                                  issued_recovery=True)
    transaction = transaction_factory(source, launcher, state, lifecycle)
    if os.path.lexists(transaction.journal):
        record = transaction._journal_record()
        if record['id'] != identifier:
            raise Refused('manager_recovery_attempt_changed')
        if record['phase'] in TERMINAL:
            raise Refused('manager_terminal_cleanup_requires_review')
        folder = safe_path(state / identifier, directory=True)
        saved = folder / 'manager-release.json'
        if (os.path.lexists(saved) and
                safe_path(saved).read_bytes() != signed):
            raise Refused('manager_recovery_release_changed')
        result = transaction.recover()
    else:
        result = transaction.abort_handoff_before_journal(signed, identifier)
    report_result(state, identifier, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Recover an existing Manager update')
    parser.add_argument('--recover-existing', action='store_true')
    args = parser.parse_args(argv)
    if not args.recover_existing:
        raise Refused('manager_explicit_recovery_required')
    home = Path.home()
    source = home / 'Downloads' / 'rap-brain'
    launcher = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
        'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources' /
        'launch_manager.py')
    state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
    result = recover_existing(source, launcher, state)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get('state') in ('aborted', 'rolled_back') else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('REPRISE REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
