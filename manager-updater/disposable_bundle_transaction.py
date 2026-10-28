"""Byte-exact disposable app bundle update/rollback drill.

No production path is accepted. No processes, networking, signatures, or
installed files are accessed. A test supplies the signed-verified boolean,
which is NOT a real signature verifier.
"""
import hashlib
import os
import stat
import tempfile
from pathlib import Path

class BundleRefused(ValueError): pass

def inventory(root):
    root=Path(root)
    if root.is_symlink() or not root.is_dir() or root.name!="DisposableBundleFixture.app":
        raise BundleRefused("Not an isolated fixture")
    result={}
    for parent,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            entry=Path(parent)/name
            mode=entry.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise BundleRefused("Symlink or special file")
            if stat.S_ISREG(mode):
                rel=str(entry.relative_to(root))
                if entry.stat().st_size > 2_000_000:raise BundleRefused("Oversize file")
                result[rel]=(hashlib.sha256(entry.read_bytes()).hexdigest(),stat.S_IMODE(mode))
    return result

def replace_atomic(target,payload,mode):
    fd,stage=tempfile.mkstemp(prefix=".candidate-",dir=target.parent)
    try:
        with os.fdopen(fd,"wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(stage,mode)
        os.replace(stage,target)
    finally:
        if os.path.exists(stage):os.unlink(stage)

def drill(root,*,signed_verified,healthy):
    root=Path(root)
    before=inventory(root)
    rel="Contents/Resources/manager.py"
    if rel not in before or "Contents/Info.plist" not in before:
        raise BundleRefused("Incomplete dummy bundle")
    if signed_verified is not True:raise BundleRefused("Signature verification absent")
    target=root/rel
    old=target.read_bytes()
    original_mode=stat.S_IMODE(target.stat().st_mode)
    candidate=old+b"\n# FIXTURE_CHANGED\n"
    try:
        replace_atomic(target,candidate,original_mode)
        if healthy is not True:
            replace_atomic(target,old,original_mode)
            if inventory(root)!=before:raise BundleRefused("Rollback mismatch")
            return "ROLLED_BACK"
        if target.read_bytes()!=candidate:raise BundleRefused("Candidate mismatch")
        return "COMMITTED_FIXTURE"
    except BaseException:
        if target.exists() and target.read_bytes()!=old:
            replace_atomic(target,old,original_mode)
        raise
