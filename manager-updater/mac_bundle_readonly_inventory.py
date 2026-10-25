#!/usr/bin/env python3
"""Read-only inventory of Rap Brain Manager bundle. Does not read app scripts, user data or secrets."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

app = Path.home() / "Applications" / "Rap Brain Manager.app"
allowed = ["Contents/Info.plist", "Contents/PkgInfo", "Contents/MacOS", "Contents/Resources", "Contents/Resources/manager.py", "Contents/Resources/publisher_key.swift", "Contents/Resources/demo_release/manifest.json"]
def describe(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"present": False}
    if stat.S_ISLNK(info.st_mode):
        return {"present": True, "type": "symlink", "refused": True}
    if stat.S_ISDIR(info.st_mode):
        if path.name in ("MacOS", "Resources"):
            return {"present": True, "type": "directory", "entries": sorted(p.name for p in path.iterdir())[:40]}
        return {"present": True, "type": "directory"}
    if not stat.S_ISREG(info.st_mode):
        return {"present": True, "type": "unexpected", "refused": True}
    # Hashes, sizes and modes only: NEVER emit contents or authentication tokens.
    record = {"present": True, "type": "regular-file", "size": info.st_size, "mode": oct(stat.S_IMODE(info.st_mode))}
    if info.st_size <= 2_000_000:
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return record

def main():
    if not app.is_dir() or app.is_symlink():
        print("NOT FOUND OR UNSAFE: installed app bundle");return 1
    print("READ-ONLY APP BUNDLE INVENTORY")
    print("App location: ~/Applications/Rap Brain Manager.app")
    for relative in allowed:
        print(relative, json.dumps(describe(app / relative), sort_keys=True, ensure_ascii=False))
    # Never enter ~/Downloads/rap-brain nor ~/.config nor private signing key.
    print("NO CHANGES MADE. NO APP CONTENTS, TOKENS OR PRIVATE KEYS PRINTED.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
