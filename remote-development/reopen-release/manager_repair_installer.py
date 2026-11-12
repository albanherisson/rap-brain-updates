#!/usr/bin/env python3
"""Finder entry for the signed, offline repair of the existing Beta 14 app."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

from creative_release import Refused, digest
from creative_transaction import safe_path
from mac_final_readonly_probe import coarse_process_inventory
from mac_install_agent import (REMOTE_INSTALL_BRIDGE_SHA, REMOTE_INSTALL_FILES,
    REMOTE_TRIAL_INSTALLED_SHA, paths, upgrade_manager_bridge)
from mac_manager_install_request import restart_foreign_server
from mac_offline_bootstrap_gate import assert_offline
from manager_repair_release import ARCHIVE, BRIDGE_ADAPTER, CHANNEL, MAX_ARCHIVE, SERVER, verify_release
from manager_repair_rehearsal import rehearse_on_copy
from manager_repair_transaction import OfflineManagerRepair
from strict_json import parse_signed_json


ADAPTER_NAME = 'mac_manager_install_request.py'
BRIDGE_BEFORE = REMOTE_TRIAL_INSTALLED_SHA | {'mac_bridge.py': REMOTE_INSTALL_BRIDGE_SHA} | REMOTE_INSTALL_FILES


def bridge_baseline(home):
    data, agent = paths(home)
    safe_path(agent)
    if data.resolve() != data:
        raise Refused('manager_repair_bridge_path_changed')
    for name, expected in BRIDGE_BEFORE.items():
        actual = digest(safe_path(data / name).read_bytes())
        allowed = (expected, BRIDGE_ADAPTER) if name == ADAPTER_NAME else (expected,)
        if actual not in allowed:
            raise Refused('manager_repair_bridge_baseline_changed')
    return digest(safe_path(data / ADAPTER_NAME).read_bytes())


def update_bridge(home, adapter):
    if digest(adapter) != BRIDGE_ADAPTER:
        raise Refused('manager_repair_bridge_payload_changed')
    if bridge_baseline(home) == BRIDGE_ADAPTER:
        return
    with tempfile.TemporaryDirectory(prefix='rapbrain-bridge-adapter-') as name:
        directory = Path(name).resolve()
        (directory / ADAPTER_NAME).write_bytes(adapter)
        upgrade_manager_bridge(home, directory, subprocess.run, BRIDGE_BEFORE,
                               {ADAPTER_NAME: BRIDGE_ADAPTER})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise Refused('manager_repair_redirect_refused')


def fetch(url, limit):
    if url not in (CHANNEL, ARCHIVE):
        raise Refused('manager_repair_channel_changed')
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(url, headers={
            'Accept-Encoding': 'identity'}), timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise Refused('manager_repair_channel_changed')
        raw = response.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise Refused('manager_repair_download_size')
    return raw


def embedded_downloader(directory):
    """Use the one-time signed release packed in the Finder app, if present."""
    directory = safe_path(directory, directory=True)
    files = {CHANNEL: directory / 'signed-release.json',
             ARCHIVE: directory / 'repair-16.zip'}
    present = [os.path.lexists(path) for path in files.values()]
    if not any(present):
        return None
    if not all(present):
        raise Refused('manager_repair_embedded_incomplete')
    def read(url, limit):
        if url not in files:
            raise Refused('manager_repair_embedded_url_changed')
        path = safe_path(files[url])
        if path.stat().st_size > limit:
            raise Refused('manager_repair_embedded_size')
        return path.read_bytes()
    return read


def install_from_channel(source, launcher, state, *, downloader=fetch,
                         transaction_factory=OfflineManagerRepair,
                         rehearsal=rehearse_on_copy, inspector=None,
                         pinned_key=None):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    opts = {'inspector': inspector} if inspector else {}
    assert_offline(source, launcher, **opts)
    if pinned_key is not None:
        opts['pinned_key'] = pinned_key
    transaction = transaction_factory(source, launcher, state, **opts)
    # A pending attempt must use the publication it already saved, even if
    # that publication expired or GitHub changed after the interruption.
    if os.path.lexists(Path(state) / 'manager-reopen-repair.json'):
        return transaction.install()
    signed = downloader(CHANNEL, 65536)
    archive = downloader(ARCHIVE, MAX_ARCHIVE)
    verify_release(signed, archive, **({'pinned_key': pinned_key}
                                      if pinned_key is not None else {}))
    report = rehearsal(source, launcher, state, signed, archive,
                       **({'pinned_key': pinned_key}
                          if pinned_key is not None else {}))
    if (type(report) is not dict or report != {'state': 'passed',
            'active_files_modified': False, 'live_database_opened': False,
            'live_configuration_opened': False}):
        raise Refused('manager_repair_rehearsal_not_proven')
    return transaction.install(signed, archive)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Rap Brain Manager repair')
    parser.add_argument('--install-signed', action='store_true')
    args = parser.parse_args(argv)
    if not args.install_signed:
        raise Refused('explicit_install_action_required')
    home = Path.home().resolve()
    source = home / 'Downloads' / 'rap-brain'
    launcher = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
        'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources' /
        'launch_manager.py')
    state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
    embedded = embedded_downloader(Path(__file__).resolve().parent)
    if embedded is None:
        raise Refused('manager_repair_embedded_release_required')
    signed = embedded(CHANNEL, 65536)
    archive = embedded(ARCHIVE, MAX_ARCHIVE)
    journal = state / 'manager-reopen-repair.json'
    issued = parse_signed_json(signed)['signed_payload']['issued_at']
    _, files, _ = verify_release(signed, archive, now=issued if journal.is_file() else None)
    bridge_baseline(home)
    processes = coarse_process_inventory(source, launcher.parent)
    if processes['manager_process_seen']:
        raise Refused('rapbrain_or_manager_still_running')
    if processes['server_process_seen'] or processes['port_8765_listening']:
        restart_foreign_server(home, {'expected_server_sha256': SERVER})
    result = install_from_channel(source, launcher, state,
                                  downloader=embedded)
    if result.get('state') == 'committed':
        try:
            update_bridge(home, files['bridge/' + ADAPTER_NAME])
        except (OSError, ValueError, RuntimeError) as error:
            raise Refused('manager_repair_committed_bridge_update_pending') from error
        result['bridge'] = 'compatible_adapter_installed'
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get('state') != 'committed':
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('REPARATION REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
