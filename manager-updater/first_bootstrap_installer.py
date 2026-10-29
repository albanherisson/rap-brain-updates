#!/usr/bin/env python3
"""External first-bootstrap entrypoint, not a released Mac installer.

The old Beta 14 app and unguarded server must be offline. It never stops an
existing process or handles a private signing key. The GitHub channel has no
production manifest yet; no executable/one-click distribution is published.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from bootstrap_download import download_bootstrap
from bootstrap_full_release import verify_full_bootstrap, verify_full_manifest
from bootstrap_full_transaction import FullBootstrapTransaction
from bootstrap_release import PUBLISHER_PIN
from creative_release import Refused
from creative_transaction import safe_path
from mac_final_readonly_probe import coarse_process_inventory
from mac_offline_bootstrap_gate import assert_offline
from offline_bootstrap_lifecycle import MacOfflineBootstrapLifecycle
from strict_json import parse_signed_json


def install_from_channel(source, launcher, state, *,
                         inspector=coarse_process_inventory,
                         downloader=download_bootstrap,
                         lifecycle_factory=MacOfflineBootstrapLifecycle,
                         pinned_key=PUBLISHER_PIN):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    dashboard = safe_path(launcher.parent / 'dashboard_beta14.html')
    # Refuse the owner's observed active state before touching the network or
    # making a backup directory. The lifecycle repeats this proof throughout.
    assert_offline(source, launcher, inspector=inspector)
    state = Path(state).absolute()
    # A switched candidate no longer matches the release baseline. Resume a
    # pending local journal with its previously authenticated release, without
    # fetching a fresh channel or relying on the release still being online.
    journal = state / 'bootstrap-transaction.json'
    if os.path.lexists(journal):
        probe = FullBootstrapTransaction(source, launcher, state,
                                         pinned_key=pinned_key)
        record = probe._journal_full()
        if record['phase'] not in ('committed', 'rolled_back', 'aborted',
                                   'restored_stopped'):
            folder = safe_path(state / record['id'], directory=True)
            raw = safe_path(folder / 'full-release.json').read_bytes()
            signed = parse_signed_json(raw)['signed_payload']
            issued = signed['issued_at']
            originals = tuple(safe_path(folder / ('before-' + name)).read_bytes()
                              for name in ('server.py', 'launch_manager.py',
                                           'dashboard_beta14.html'))
            manifest = verify_full_manifest(raw, *originals,
                                            pinned_key=pinned_key, now=issued)
            lifecycle = lifecycle_factory(source, launcher, state, manifest,
                                          inspector=inspector)
            transaction = FullBootstrapTransaction(source, launcher, state,
                                                   lifecycle, pinned_key=pinned_key)
            return transaction.install(b'', b'')
    originals = (safe_path(source / 'server.py').read_bytes(), launcher.read_bytes(),
                 dashboard.read_bytes())
    raw, archive, manifest = downloader(*originals, pinned_key=pinned_key)
    verified, _ = verify_full_bootstrap(raw, archive, *originals,
                                        pinned_key=pinned_key)
    if manifest != verified:
        raise Refused('bootstrap_download_manifest_changed')
    lifecycle = lifecycle_factory(source, launcher, state, manifest,
                                  inspector=inspector)
    transaction = FullBootstrapTransaction(source, launcher, state, lifecycle,
                                            pinned_key=pinned_key)
    return transaction.install(raw, archive)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Rap Brain first signed bootstrap')
    parser.add_argument('--install-signed', action='store_true')
    args = parser.parse_args(argv)
    if not args.install_signed:
        raise Refused('explicit_install_action_required')
    home = Path.home()
    source = home / 'Downloads' / 'rap-brain'
    launcher = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
        'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources' /
        'launch_manager.py')
    state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
    result = install_from_channel(source, launcher, state)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get('state') == 'committed' else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('INSTALLATION REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
