#!/usr/bin/env python3
"""Persist a NON-EXECUTABLE Manager AST candidate to dedicated development folder.

This never imports/executes the candidate, accesses Rap Brain libraries, or
modifies the installed bundle. Refuses output that already exists.
"""
import hashlib,os,stat
from pathlib import Path
from mac_build_isolated_manager_candidate import TARGET,PIN,transform
ROOT=Path.home()/"Library/Application Support/RapBrainManager/isolated-dryrun"
OUT=ROOT/"non-executable-source-preview-v1"
NAME="manager_candidate.py.DISABLED"
def write_candidate(raw,output):
    if hashlib.sha256(raw).hexdigest()!=PIN:raise ValueError("untrusted original")
    if output.exists() or output.is_symlink():raise ValueError("output exists")
    parent=output.parent
    if not parent.is_dir() or parent.is_symlink():raise ValueError("untrusted output directory")
    parent.mkdir(exist_ok=True)
    patched,h,p=transform(raw)
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(patched);f.flush();os.fsync(f.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return h,p,hashlib.sha256(patched).hexdigest()
def main():
    if TARGET.is_symlink():raise SystemExit("REFUS: symlink original")
    meta=TARGET.lstat()
    if not stat.S_ISREG(meta.st_mode) or not 0<meta.st_size<=100000:raise SystemExit("REFUS: source")
    if not ROOT.is_dir() or ROOT.is_symlink():raise SystemExit("REFUS: isolated root unavailable")
    if OUT.exists() or OUT.is_symlink():raise SystemExit("REFUS: output already present")
    OUT.mkdir(mode=0o700)
    try:
        h,p,digest=write_candidate(TARGET.read_bytes(),OUT/NAME)
    except BaseException:
        OUT.rmdir()
        raise
    print("OK: candidate archived in isolated development folder, never run")
    print("OK: home references:",h,"subprocess calls blocked:",p)
    print("SHA256:",digest)
    print("PATH:",OUT/NAME)
    print("SAFE STATE: filename DISABLED, no launch, no installed change")
if __name__=="__main__":main()
