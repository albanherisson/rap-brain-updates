"""Strict path confinement for a future disposable Manager runner.

This module intentionally contains no launch / update functionality.
Untrusted paths must be refused, not silently rewritten.
"""
import os
import stat
from pathlib import Path

class PathEscape(ValueError):
    pass

def confined_path(root, relative):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise PathEscape("invalid sandbox root")
    if not isinstance(relative,str) or not relative or "\\x00" in relative:
        raise PathEscape("invalid relative path")
    candidate=Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise PathEscape("non-relative path")
    anchor=root.resolve(strict=True)
    current=root
    for part in candidate.parts:
        if part in ("",".",".."):raise PathEscape("invalid component")
        current=current/part
        if current.is_symlink():
            raise PathEscape("symlink within path")
        if current.exists():
            kind=current.lstat().st_mode
            if not (stat.S_ISDIR(kind) or stat.S_ISREG(kind)):
                raise PathEscape("special path")
    resolved=(root/candidate).resolve(strict=False)
    if not resolved.is_relative_to(anchor):
        raise PathEscape("path escapes root")
    return resolved

def sanitized_environment(home, base=None):
    home=Path(home)
    if home.is_symlink() or not home.is_dir():
        raise PathEscape("invalid sandbox home")
    h=str(home.resolve(strict=True))
    # A strict allowlist, rather than inherited user environment.
    return {"HOME":h,"TMPDIR":h,"XDG_CONFIG_HOME":h,
            "XDG_DATA_HOME":h,"XDG_CACHE_HOME":h,
            "PATH":"/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONDONTWRITEBYTECODE":"1"}
