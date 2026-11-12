#!/usr/bin/env python3
"""Repair only a disallowed FinderInfo xattr after a verified Mac app copy drill.

Preserves a private original app copy and its FinderInfo value. Does not read
or modify Rap Brain's server, library, SQLite database or Ollama configuration.
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
FINDER_INFO = 'com.apple.FinderInfo'


def run(args, *, timeout=90):
    return subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                          timeout=timeout)


def checked(args):
    result = run(args)
    if result.returncode:
        raise ValueError('copy_or_xattr_command_failed')
    return result.stdout


def finderinfo(path):
    result = run(['/usr/bin/xattr', '-px', FINDER_INFO, str(path)])
    if result.returncode:
        raise ValueError('finderinfo_missing_or_unreadable')
    hex_value = re.sub(rb'\s+', b'', result.stdout)
    if (not 2 <= len(hex_value) <= 4096 or len(hex_value) % 2 or
            not re.fullmatch(rb'[0-9a-fA-F]+', hex_value)):
        raise ValueError('finderinfo_invalid')
    return hex_value.decode('ascii').lower()


def fingerprint(app):
    app = Path(app)
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
        files[str(path.relative_to(app))] = [hashlib.sha256(path.read_bytes()).hexdigest(),
                                            stat.S_IMODE(mode)]
    if not files or 'Contents/Resources/launch_manager.py' not in files:
        raise ValueError('app_incomplete')
    return files


def verify_signature(app):
    return run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                '--verbose=2', str(app)])


def repair(home):
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    home = Path(home).absolute()
    app = home / APP_RELATIVE
    backup_root = home / 'Downloads/RapBrainManagerBackups'
    if (any(path.is_symlink() for path in (app, *app.parents, backup_root)) or
            not backup_root.is_dir() or app.stat().st_uid != os.getuid()):
        raise ValueError('app_or_backup_path_unsafe')
    baseline = fingerprint(app)
    value = finderinfo(app)
    failure = verify_signature(app)
    if failure.returncode == 0:
        raise ValueError('app_signature_already_valid')
    if b'Disallowed xattr com.apple.FinderInfo' not in failure.stderr + failure.stdout:
        detail = (failure.stderr + failure.stdout).decode(errors='replace')[-350:]
        raise ValueError('signature_failure_not_only_finderinfo: ' + detail)
    repair_root = backup_root / 'signature-repairs'
    if repair_root.is_symlink():
        raise ValueError('repair_backup_symlink_refused')
    repair_root.mkdir(mode=0o700, exist_ok=True)
    if repair_root.stat().st_uid != os.getuid() or repair_root.stat().st_mode & 0o077:
        raise ValueError('repair_backup_permissions_unsafe')
    folder = repair_root / ('finderinfo-' + uuid.uuid4().hex)
    folder.mkdir(mode=0o700)
    saved = folder / 'original.app'
    checked(['/usr/bin/ditto', str(app), str(saved)])
    if fingerprint(saved) != baseline or finderinfo(saved) != value:
        raise ValueError('app_backup_mismatch')
    value_path = folder / 'finderinfo.hex'
    fd = os.open(value_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    with tempfile.TemporaryDirectory(prefix='finderinfo-copy-', dir=backup_root) as temp:
        trial = Path(temp) / 'trial.app'
        checked(['/usr/bin/ditto', str(saved), str(trial)])
        if fingerprint(trial) != baseline or finderinfo(trial) != value:
            raise ValueError('app_trial_copy_mismatch')
        checked(['/usr/bin/xattr', '-d', FINDER_INFO, str(trial)])
        if fingerprint(trial) != baseline or verify_signature(trial).returncode:
            raise ValueError('stripped_copy_signature_invalid')
        checked(['/usr/bin/xattr', '-wx', FINDER_INFO, value, str(trial)])
        if fingerprint(trial) != baseline or finderinfo(trial) != value:
            raise ValueError('finderinfo_restore_drill_failed')
    if (fingerprint(saved) != baseline or finderinfo(saved) != value or
            fingerprint(app) != baseline or finderinfo(app) != value):
        raise ValueError('app_changed_before_repair')
    checked(['/usr/bin/xattr', '-d', FINDER_INFO, str(app)])
    if fingerprint(app) != baseline or verify_signature(app).returncode:
        # Restore only the original root attribute; all code bytes stay intact.
        checked(['/usr/bin/xattr', '-wx', FINDER_INFO, value, str(app)])
        if fingerprint(app) != baseline or finderinfo(app) != value:
            raise ValueError('active_finderinfo_restore_failed')
        raise ValueError('active_signature_still_invalid_restored')
    return {'state':'repaired', 'app_code_bytes_changed':False,
            'rapbrain_data_accessed':False, 'backup':str(folder)}


if __name__ == '__main__':
    try:
        print(json.dumps(repair(Path.home()), sort_keys=True))
    except Exception as exc:
        print('REPARATION REFUSEE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
