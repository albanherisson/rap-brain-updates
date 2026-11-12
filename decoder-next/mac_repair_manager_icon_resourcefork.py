#!/usr/bin/env python3
"""Remove only an oversized Finder Icon resource fork after a copy drill.

The original app and icon fork remain in a private backup. No Rap Brain code,
database, library, analysis or Ollama configuration is opened or changed.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import uuid


APP_RELATIVE = ('Downloads/RapBrainManager_App_Beta14/'
                'Rap Brain Manager Beta 14.app')
ATTRIBUTE = 'com.apple.ResourceFork'
MAX_FORK = 10_000_000


def run(argv, *, timeout=90):
    return subprocess.run(argv, capture_output=True, stdin=subprocess.DEVNULL,
                          timeout=timeout)


def checked(argv):
    result = run(argv)
    if result.returncode:
        raise ValueError('copy_or_xattr_command_failed')
    return result.stdout


def signature(app):
    result = run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])
    if result.returncode:
        raise ValueError('app_signature_invalid')


def fingerprint(app):
    if app.is_symlink() or not app.is_dir():
        raise ValueError('app_layout_invalid')
    files = {}
    for path in sorted(app.rglob('*')):
        if path.is_symlink():
            raise ValueError('app_symlink_refused')
        if path.is_dir():
            continue
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode):
            raise ValueError('app_special_file_refused')
        files[str(path.relative_to(app))] = (
            hashlib.sha256(path.read_bytes()).hexdigest(), stat.S_IMODE(mode))
    if (not any(name in files for name in ('Icon', 'Icon\r')) or
            'Contents/Resources/launch_manager.py' not in files):
        raise ValueError('app_incomplete')
    return files


def fork(path):
    raw = checked(['/usr/bin/xattr', '-px', ATTRIBUTE, str(path)])
    compact = re.sub(rb'\s+', b'', raw)
    if (not 600_000 < len(compact) <= MAX_FORK * 2 or len(compact) % 2 or
            not re.fullmatch(rb'[0-9a-fA-F]+', compact)):
        raise ValueError('icon_resourcefork_unexpected_size')
    value = bytes.fromhex(compact.decode('ascii'))
    return len(value), hashlib.sha256(value).hexdigest()


def assert_no_fork(path):
    result = run(['/usr/bin/xattr', str(path)])
    if result.returncode or ATTRIBUTE.encode() in result.stdout.splitlines():
        raise ValueError('icon_resourcefork_still_present')


def signed_backup_module(app, state):
    sys.path.insert(0, str(app / 'Contents/Resources'))
    from manager_helper_release import verify_staged
    helper = verify_staged(state)
    sys.path.insert(0, str(helper))
    from app_bundle_backup import save_app_backup, inventory
    return save_app_backup, inventory


def repair(home):
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    home = Path(home).absolute()
    app = home / APP_RELATIVE
    icons = [app / name for name in ('Icon', 'Icon\r')
             if (app / name).exists() or (app / name).is_symlink()]
    if len(icons) != 1:
        raise ValueError('finder_icon_path_ambiguous')
    icon = icons[0]
    backup_root = home / 'Downloads/RapBrainManagerBackups'
    state = backup_root / 'secure-update'
    if (any(path.is_symlink() for path in (app, icon, backup_root, state)) or
            not backup_root.is_dir() or not state.is_dir() or
            app.stat().st_uid != os.getuid() or
            not icon.is_file() or icon.stat().st_uid != os.getuid()):
        raise ValueError('app_or_backup_path_unsafe')
    if any((state / name).exists() or (state / name).is_symlink() for name in
           ('maintenance.ticket', 'bootstrap-intent.json', 'maintenance-intent.json')):
        raise ValueError('maintenance_in_progress')
    before = fingerprint(app)
    original_fork = fork(icon)
    signature(app)
    save_app_backup, inventory = signed_backup_module(app, state)

    repair_root = backup_root / 'signature-repairs'
    if repair_root.is_symlink():
        raise ValueError('repair_backup_symlink_refused')
    repair_root.mkdir(mode=0o700, exist_ok=True)
    if repair_root.stat().st_uid != os.getuid() or repair_root.stat().st_mode & 0o077:
        raise ValueError('repair_backup_permissions_unsafe')
    folder = repair_root / ('icon-fork-' + uuid.uuid4().hex)
    folder.mkdir(mode=0o700)
    saved = folder / 'original.app'
    checked(['/usr/bin/ditto', str(app), str(saved)])
    if fingerprint(saved) != before or fork(saved / icon.name) != original_fork:
        raise ValueError('app_backup_mismatch')
    signature(saved)

    with tempfile.TemporaryDirectory(prefix='icon-fork-copy-', dir=repair_root) as temp:
        root = Path(temp)
        trial = root / 'trial.app'
        checked(['/usr/bin/ditto', str(saved), str(trial)])
        if fingerprint(trial) != before or fork(trial / icon.name) != original_fork:
            raise ValueError('app_trial_copy_mismatch')
        checked(['/usr/bin/xattr', '-d', ATTRIBUTE, str(trial / icon.name)])
        assert_no_fork(trial / icon.name)
        if fingerprint(trial) != before:
            raise ValueError('app_code_changed_on_copy')
        signature(trial)
        # Exercise the exact installed backup and separate restore drill.
        drill = root / 'backup'
        drill.mkdir(mode=0o700)
        save_app_backup(trial, drill)
        inventory(trial)
        # Rehearse restoration of the original icon, including its large fork.
        checked(['/usr/bin/ditto', str(saved / icon.name), str(trial / icon.name)])
        if fingerprint(trial) != before or fork(trial / icon.name) != original_fork:
            raise ValueError('icon_fork_restore_drill_failed')
        signature(trial)

    if fingerprint(app) != before or fork(icon) != original_fork:
        raise ValueError('app_changed_before_repair')
    signature(app)
    checked(['/usr/bin/xattr', '-d', ATTRIBUTE, str(icon)])
    try:
        assert_no_fork(icon)
        if fingerprint(app) != before:
            raise ValueError('active_app_code_changed')
        signature(app)
        inventory(app)
    except Exception:
        checked(['/usr/bin/ditto', str(saved / icon.name), str(icon)])
        if fingerprint(app) != before or fork(icon) != original_fork:
            raise ValueError('active_icon_restore_failed')
        signature(app)
        raise
    return {'state':'repaired', 'app_code_bytes_changed':False,
            'rapbrain_data_accessed':False, 'backup':str(folder),
            'icon_fork_sha256':original_fork[1]}


if __name__ == '__main__':
    try:
        print(json.dumps(repair(Path.home()), sort_keys=True))
    except Exception as exc:
        print('REPARATION REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
