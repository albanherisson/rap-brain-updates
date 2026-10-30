#!/usr/bin/env python3
"""External Finder entry for a Manager-signed, one-time Creative key rotation."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request

from creative_release import Refused
from creative_transaction import safe_path
from creative_trust_rotation import verify_rotation
from creative_trust_transaction import OfflineTrustRotation
from mac_offline_bootstrap_gate import assert_offline


CHANNEL = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
           'main/manager-trust/creative-rotation-1.json')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise Refused('trust_rotation_redirect_refused')


def download():
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(CHANNEL,
            headers={'Accept-Encoding': 'identity'}), timeout=20) as response:
        if response.status != 200 or response.geturl() != CHANNEL:
            raise Refused('trust_rotation_channel_changed')
        raw = response.read(16_385)
    if not 0 < len(raw) <= 16_384:
        raise Refused('trust_rotation_channel_size')
    return raw


def install_from_channel(source, launcher, state, *, downloader=download):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    assert_offline(source, launcher)
    transaction = OfflineTrustRotation(source, launcher, state)
    # Recover a pending local attempt using its private backup, even if the
    # network release has expired or disappeared. No fresh request in recovery.
    if os.path.lexists(Path(state) / 'trust-rotation.json'):
        return transaction.install(b'')
    raw = downloader()
    verify_rotation(raw, safe_path(launcher.parent / 'creative_release.py').read_bytes())
    return transaction.install(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Rap Brain Creative trust rotation')
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
