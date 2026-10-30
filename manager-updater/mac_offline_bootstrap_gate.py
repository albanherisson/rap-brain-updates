"""Fail-closed prerequisites for a one-time external Mac bootstrap.

Never stops a process. The owner must close the old app/server first; the old
unguarded server cannot be safely attached to or stopped by PID. Local app
re-signing is allowed only after a full verified app backup exists.
"""
import os
from pathlib import Path
import subprocess
import sys

from app_bundle_backup import inventory, read_app_backup
from creative_release import Refused
from creative_transaction import safe_path
from mac_final_readonly_probe import coarse_process_inventory


def assert_offline(source, launcher, *, inspector=coarse_process_inventory):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    if not callable(inspector):
        raise Refused('offline_inspector_required')
    try:
        report = inspector(source, launcher.parent)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise Refused('offline_inventory_unavailable') from exc
    if (type(report) is not dict or report.keys() !=
            {'server_process_seen', 'manager_process_seen', 'port_8765_listening'} or
            any(type(value) is not bool for value in report.values())):
        raise Refused('offline_inventory_invalid')
    if any(report.values()):
        raise Refused('rapbrain_or_manager_still_running')
    return True


def resign_verified_app(app, backup_folder, source, launcher, *,
                        inspector=coarse_process_inventory):
    """Ad-hoc re-sign the stopped app after proving its complete backup."""
    if sys.platform != 'darwin':
        raise Refused('macos_required_for_app_signature')
    app = safe_path(app, directory=True)
    if app.suffix != '.app' or app.is_symlink():
        raise Refused('app_bundle_required')
    assert_offline(source, launcher, inspector=inspector)
    read_app_backup(backup_folder)
    if app.stat().st_uid != os.getuid():
        raise Refused('app_owner_changed')
    # A detached signature can live in extended attributes on a script
    # executable. Prove the *backup* is launchable before touching the live
    # app's signature or any of its resources.
    backup_app = safe_path(Path(backup_folder) / 'app-original.app', directory=True)
    try:
        backup_check = subprocess.run(
            ['/usr/bin/codesign', '--verify', '--deep', '--strict', str(backup_app)],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=90)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('app_backup_signature_tool_unavailable') from exc
    if backup_check.returncode != 0:
        raise Refused('app_backup_signature_invalid')
    for args in (('/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app)),
                 ('/usr/bin/codesign', '--verify', '--deep', '--strict', str(app))):
        try:
            result = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                                    timeout=90)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Refused('app_signature_tool_unavailable') from exc
        if result.returncode != 0:
            raise Refused('app_signature_failed')
    assert_offline(source, launcher, inspector=inspector)
    return True


def verify_restored_app(app, backup_folder, source, launcher, *,
                        inspector=coarse_process_inventory):
    """Check exact restored bytes and existing signature, without re-signing."""
    if sys.platform != 'darwin':
        raise Refused('macos_required_for_app_signature')
    app = safe_path(app, directory=True)
    assert_offline(source, launcher, inspector=inspector)
    if inventory(app) != read_app_backup(backup_folder):
        raise Refused('restored_app_not_identical')
    try:
        result = subprocess.run(
            ['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=90)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('app_signature_tool_unavailable') from exc
    if result.returncode != 0:
        raise Refused('restored_app_signature_invalid')
    assert_offline(source, launcher, inspector=inspector)
    return True


def verify_unchanged_app(app, source, launcher, *,
                         inspector=coarse_process_inventory):
    """Read-only signature check before any app backup completed."""
    if sys.platform != 'darwin':
        raise Refused('macos_required_for_app_signature')
    app = safe_path(app, directory=True)
    assert_offline(source, launcher, inspector=inspector)
    try:
        result = subprocess.run(
            ['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=90)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('app_signature_tool_unavailable') from exc
    if result.returncode != 0:
        raise Refused('unchanged_app_signature_invalid')
    assert_offline(source, launcher, inspector=inspector)
    return True
