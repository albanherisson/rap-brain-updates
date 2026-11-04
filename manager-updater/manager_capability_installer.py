#!/usr/bin/env python3
"""Finder entry for the one-time Manager-key signed general-update capability."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request

from creative_release import Refused
from creative_transaction import safe_path
from mac_offline_bootstrap_gate import assert_offline
from manager_capability_release import (ARCHIVE, CHANNEL, MAX_ARCHIVE,
                                        verify_release)
from manager_capability_transaction import OfflineManagerCapability


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise Refused('manager_capability_redirect_refused')


def fetch(url, limit):
    if url not in (CHANNEL, ARCHIVE):
        raise Refused('manager_capability_channel_changed')
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(url,
            headers={'Accept-Encoding': 'identity'}), timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise Refused('manager_capability_channel_changed')
        raw = response.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise Refused('manager_capability_download_size')
    return raw


def install_from_channel(source, launcher, state, *, downloader=fetch,
                         transaction_factory=OfflineManagerCapability,
                         inspector=None, pinned_key=None):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    options = {'inspector': inspector} if inspector else {}
    assert_offline(source, launcher, **options)
    tx_options = dict(options)
    if pinned_key is not None:
        tx_options['pinned_key'] = pinned_key
    transaction = transaction_factory(source, launcher, state, **tx_options)
    # The previous attempt owns its saved publication. Never fetch again to
    # recover, including when the original publication has expired.
    if os.path.lexists(Path(state) / 'manager-capability.json'):
        return transaction.install()
    raw = downloader(CHANNEL, 65536)
    archive = downloader(ARCHIVE, MAX_ARCHIVE)
    verify_args = {'pinned_key': pinned_key} if pinned_key is not None else {}
    verify_release(raw, archive, **verify_args)
    return transaction.install(raw, archive)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Rap Brain Manager capability')
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
