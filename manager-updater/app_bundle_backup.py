"""Exact private backup and separate restore drill of a stopped macOS app.

This preserves executable and code-signature resources, which can change when
the staged app is locally re-signed. Refuses symlinks, special files, unexpected
new files and changed backup bytes. Does not run codesign or touch Rap Brain data.
"""
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from creative_release import Refused
from creative_transaction import atomic_write, fsync_dir, safe_path
from app_xattrs import MAX_ATTR, get_attr, list_attrs, set_attr


MAX_FILES = 1000
MAX_BYTES = 100_000_000
MAX_XATTR_BYTES = 1_000_000


def file_xattrs(path):
    """Preserve detached signatures on script executables as well as bytes."""
    names = list_attrs(path)
    if len(names) > 32:
        raise Refused('app_bundle_xattr_limit')
    result = {}
    for name in names:
        if not isinstance(name, str) or not 0 < len(name) <= 200 or not all(
                32 <= ord(c) < 127 for c in name):
            raise Refused('app_bundle_xattr_name')
        value = get_attr(path, name)
        if len(value) > MAX_ATTR:
            raise Refused('app_bundle_xattr_limit')
        result[name] = base64.b64encode(value).decode('ascii')
    return result


def restore_xattrs(path, encoded):
    for name, value in encoded.items():
        set_attr(path, name, base64.b64decode(value, validate=True))


def inventory(app):
    app = safe_path(app, directory=True)
    if app.suffix != '.app':
        raise Refused('app_bundle_required')
    result = {}
    total = xattr_total = 0
    for base, dirs, files in os.walk(app, followlinks=False):
        for name in dirs + files:
            path = Path(base) / name
            info = path.lstat()
            if path.is_symlink() or not (stat.S_ISREG(info.st_mode) or
                                        stat.S_ISDIR(info.st_mode)):
                raise Refused('app_bundle_unsafe_entry')
            if stat.S_ISDIR(info.st_mode):
                continue
            relative = path.relative_to(app).as_posix()
            raw = path.read_bytes()
            total += len(raw)
            attrs = file_xattrs(path)
            xattr_total += sum(len(base64.b64decode(value)) for value in attrs.values())
            if (len(result) >= MAX_FILES or total > MAX_BYTES or
                    xattr_total > MAX_XATTR_BYTES):
                raise Refused('app_bundle_size_limit')
            result[relative] = {'sha256': hashlib.sha256(raw).hexdigest(),
                                'mode': stat.S_IMODE(info.st_mode),
                                'bytes': len(raw), 'xattrs': attrs}
    if not result or 'Contents/Resources/launch_manager.py' not in result:
        raise Refused('app_bundle_incomplete')
    return result


def _copy_verified(source, destination, expected):
    destination.mkdir(mode=0o700)
    for name, entry in expected.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = safe_path(source / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise Refused('app_backup_source_changed')
        atomic_write(path, raw, entry['mode'])
        restore_xattrs(path, entry['xattrs'])
    if inventory(destination) != expected:
        raise Refused('app_backup_copy_mismatch')
    fsync_dir(destination)


def save_app_backup(app, folder):
    app = safe_path(app, directory=True)
    folder = safe_path(folder, directory=True)
    expected = inventory(app)
    saved = folder / 'app-original.app'
    if os.path.lexists(saved):
        raise Refused('app_backup_already_exists')
    _copy_verified(app, saved, expected)
    atomic_write(folder / 'app-backup.json', json.dumps(expected, sort_keys=True).encode())
    # Actually restore the private backup into a second directory, then
    # compare every byte and file mode. The rehearsal never touches live app.
    with tempfile.TemporaryDirectory(prefix='app-restore-drill-', dir=folder) as temp:
        target = Path(temp) / 'restored.app'
        _copy_verified(saved, target, expected)
    fsync_dir(folder)
    return expected


def read_app_backup(folder):
    folder = safe_path(folder, directory=True)
    path = safe_path(folder / 'app-backup.json')
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise Refused('app_backup_manifest_unsafe')
    raw = path.read_bytes()
    if not 0 < len(raw) <= 1_500_000:
        raise Refused('app_backup_manifest_size')
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise Refused('app_backup_duplicate_field')
            data[key] = value
        return data
    try:
        expected = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise Refused('app_backup_manifest_invalid') from exc
    if (type(expected) is not dict or not 0 < len(expected) <= MAX_FILES or
            'Contents/Resources/launch_manager.py' not in expected):
        raise Refused('app_backup_manifest_invalid')
    total = xattr_total = 0
    for name, entry in expected.items():
        path = Path(name)
        if (type(name) is not str or path.is_absolute() or '..' in path.parts or
                path.as_posix() != name or not name.startswith('Contents/') or
                type(entry) is not dict or entry.keys() !=
                {'sha256', 'mode', 'bytes', 'xattrs'} or
                type(entry['sha256']) is not str or len(entry['sha256']) != 64 or
                any(c not in '0123456789abcdef' for c in entry['sha256']) or
                type(entry['mode']) is not int or not 0 <= entry['mode'] <= 0o777 or
                type(entry['bytes']) is not int or entry['bytes'] < 0 or
                type(entry['xattrs']) is not dict or len(entry['xattrs']) > 32):
            raise Refused('app_backup_manifest_invalid')
        total += entry['bytes']
        for attr_name, value in entry['xattrs'].items():
            if (type(attr_name) is not str or not 0 < len(attr_name) <= 200 or
                    not all(32 <= ord(c) < 127 for c in attr_name) or
                    type(value) is not str or len(value) > 133_336):
                raise Refused('app_backup_manifest_invalid')
            try:
                decoded = base64.b64decode(value, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise Refused('app_backup_manifest_invalid') from exc
            if len(decoded) > MAX_ATTR:
                raise Refused('app_backup_manifest_invalid')
            xattr_total += len(decoded)
    if total > MAX_BYTES or xattr_total > MAX_XATTR_BYTES:
        raise Refused('app_backup_manifest_size')
    saved = safe_path(folder / 'app-original.app', directory=True)
    if inventory(saved) != expected:
        raise Refused('app_backup_integrity')
    return expected


def restore_app_backup(app, folder, *, allowed_extra=()):
    app = safe_path(app, directory=True)
    expected = read_app_backup(folder)
    current = inventory(app)
    extras = set(current) - set(expected)
    if extras - set(allowed_extra):
        raise Refused('app_unexpected_extra_preserved')
    saved = folder / 'app-original.app'
    # A caller must first prove the app is stopped. Copying from the private
    # verified backup is repeatable after an interrupted rollback.
    for name, entry in expected.items():
        raw = safe_path(saved / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise Refused('app_backup_integrity')
        atomic_write(app / name, raw, entry['mode'])
        restore_xattrs(app / name, entry['xattrs'])
    for name in extras:
        path = safe_path(app / name)
        path.unlink()
    fsync_dir(app)
    if inventory(app) != expected:
        raise Refused('app_restore_integrity')
    return True
