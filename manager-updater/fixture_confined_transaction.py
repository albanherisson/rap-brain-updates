"""Disposable-only path-safe staged file replacement.

No installed Manager file is an accepted target. Atomic replacement, exact
rollback and per-file SHA checks are implemented for isolated test fixtures.
"""
import hashlib,os,stat,tempfile
from pathlib import Path
from manager_path_confinement import confined_path,PathEscape

MARKER=b"RAPBRAIN_DISPOSABLE_TRANSACTION_V1"
def digest(data):return hashlib.sha256(data).hexdigest()
def replace_fixture(root,relative,incoming,*,health):
    root=Path(root)
    if root.name!="DisposableManagerDataFixture" or root.is_symlink():
        raise PathEscape("wrong fixture root")
    marker=confined_path(root,".fixture-marker")
    if marker.read_bytes()!=MARKER:raise PathEscape("missing disposable marker")
    target=confined_path(root,relative)
    if not target.is_file() or target.is_symlink():raise PathEscape("missing normal target")
    if type(incoming) is not bytes or len(incoming)>2_000_000:
        raise ValueError("invalid candidate")
    old=target.read_bytes()
    mode=stat.S_IMODE(target.stat().st_mode)
    if len(old)>2_000_000:raise ValueError("old file exceeds cap")
    def swap(data):
        fd,name=tempfile.mkstemp(prefix=".rapbrain-stage-",dir=str(target.parent))
        try:
            with os.fdopen(fd,"wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(name,mode)
            os.replace(name,target)
            dir_fd=os.open(str(target.parent),os.O_RDONLY)
            try:os.fsync(dir_fd)
            finally:os.close(dir_fd)
        finally:
            if os.path.exists(name):os.unlink(name)
    swap(incoming)
    if not health:
        swap(old)
        if digest(target.read_bytes())!=digest(old):
            raise RuntimeError("rollback integrity mismatch")
        return "ROLLED_BACK"
    if digest(target.read_bytes())!=digest(incoming):
        swap(old)
        raise RuntimeError("commit integrity mismatch")
    return "COMMITTED_FIXTURE"
