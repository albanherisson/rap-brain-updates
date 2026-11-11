"""Bounded file extended attributes on Linux and macOS.

Python's os.*xattr functions are Linux-only. macOS uses its system xattr
utility in hex mode so script executable signatures survive app rollback.
"""
import os
import subprocess
import sys

from creative_release import Refused


MAX_ATTR = 100_000


def _mac(args, cap):
    try:
        result = subprocess.run(['/usr/bin/xattr', *args], capture_output=True,
                                timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('app_xattr_tool_unavailable') from exc
    if result.returncode != 0 or len(result.stdout) > cap or len(result.stderr) > 4096:
        raise Refused('app_xattr_tool_refused')
    return result.stdout


def list_attrs(path):
    if sys.platform != 'darwin':
        return os.listxattr(path, follow_symlinks=False)
    raw = _mac([str(path)], 8000)
    try:
        names = raw.decode('utf-8').splitlines()
    except UnicodeError as exc:
        raise Refused('app_xattr_names_invalid') from exc
    if len(names) > 32 or len(names) != len(set(names)):
        raise Refused('app_xattr_names_invalid')
    return names


def get_attr(path, name):
    if sys.platform != 'darwin':
        return os.getxattr(path, name, follow_symlinks=False)
    raw = _mac(['-px', name, str(path)], MAX_ATTR * 3)
    try:
        value = bytes.fromhex(raw.decode('ascii'))
    except (ValueError, UnicodeError) as exc:
        raise Refused('app_xattr_value_invalid') from exc
    if len(value) > MAX_ATTR:
        raise Refused('app_xattr_value_limit')
    return value


def set_attr(path, name, value):
    if len(value) > MAX_ATTR:
        raise Refused('app_xattr_value_limit')
    if sys.platform != 'darwin':
        os.setxattr(path, name, value, follow_symlinks=False)
    else:
        _mac(['-wx', name, value.hex(), str(path)], 100)
