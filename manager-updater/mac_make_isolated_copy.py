#!/usr/bin/env python3
"""Create a NON-EXECUTED, isolated backup copy of installed Rap Brain Manager.
Does not modify installed bundle, Rap Brain data or signing key."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

SOURCE = Path.home() / "Applications" / "Rap Brain Manager.app"
ROOT = Path.home() / "Library" / "Application Support" / "RapBrainManager" / "isolated-dryrun"
EXPECTED = {
    "Contents/Info.plist": "4475f3c50dfe7e0748a13158904798bfeddedd5c151ffcff43ac29027a3b4784",
    "Contents/Resources/manager.py": "bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5",
    "Contents/Resources/demo_release/manifest.json": "5628728dcbbbaeb9073d78adbfbb01519096de3f23582926db675624705d42f7",
}
LIMIT_BYTES = 100 * 1024 * 1024

def refuse(msg):
    print("REFUS:", msg, file=sys.stderr)
    raise SystemExit(1)

def hashfile(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda:handle.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()

def inspect(root):
    total = 0
    files = {}
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        for name in dirs + names:
            p = Path(current) / name
            st = p.lstat()
            if stat.S_ISLNK(st.st_mode):
                refuse("Symbolic link refused: " + str(p.relative_to(root)))
            if not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                refuse("Unusual file refused: " + str(p.relative_to(root)))
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
                if total > LIMIT_BYTES:
                    refuse("App exceeds 100 MB safe-copy limit")
                files[str(p.relative_to(root))] = (st.st_size, hashfile(p))
    return files

def main():
    if not SOURCE.is_dir() or SOURCE.is_symlink():
        refuse("Installed app missing or unsafe")
    if ROOT.is_symlink():
        refuse("Dry-run root must not be symbolic link")
    for rel, expected in EXPECTED.items():
        path = SOURCE / rel
        if not path.is_file() or path.is_symlink() or hashfile(path) != expected:
            refuse("Installed Manager differs from read-only inventory: " + rel)
    before = inspect(SOURCE)
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    ROOT.chmod(0o700)
    destination = ROOT / "Rap Brain Manager - Isolated Copy.app"
    if destination.exists() or destination.is_symlink():
        refuse("An isolated copy already exists; refusing to overwrite")
    # Create and copy into unpredictable staging directory under fixed support location.
    stage = Path(tempfile.mkdtemp(prefix="stage-", dir=ROOT))
    candidate = stage / "Rap Brain Manager - Isolated Copy.app"
    try:
        shutil.copytree(SOURCE, candidate, symlinks=False, copy_function=shutil.copy2)
        after = inspect(candidate)
        if before != after:
            refuse("Copy differs from installed bundle")
        # os.replace is atomic for same-volume move. Do not execute the copied app.
        os.rename(candidate, destination)
        print("SUCCES: isolated app copied and verified")
        print("Original: ~/Applications/Rap Brain Manager.app (unchanged)")
        print("Copy: ~/Library/Application Support/RapBrainManager/isolated-dryrun/Rap Brain Manager - Isolated Copy.app")
        print("Files verified:", len(after))
        print("No app launched; no files in Rap Brain touched")
        print("NEXT: report only this summary, never post scripts or signing keys")
    finally:
        shutil.rmtree(stage, ignore_errors=True)

if __name__ == "__main__":
    main()
