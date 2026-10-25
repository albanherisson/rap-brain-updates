#!/usr/bin/env python3
"""Create a distinct, explicitly NON-INSTALLABLE Manager lab ZIP and canonical payload.
No signing, execution, installation, network or private key access.
"""
from pathlib import Path
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import zipfile

ROOT=Path.home()/"Library/Application Support/RapBrainManager/isolated-dryrun"
SOURCE=ROOT/"Rap Brain Manager - Isolated Copy.app/Contents/Resources/manager.py"
LAB=ROOT/"distinct-unsigned-lab-1.0.6"
NAME="Rap_Brain_Manager_1.0.6_lab_distinct.zip"
OLD_SHA="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
MARKER=b"\n# RAP_BRAIN_DISTINCT_UNSIGNED_LAB_ONLY\n"

def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise ValueError("Isolated root not found")
    st=SOURCE.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size>2000000:
        raise ValueError("Unsafe isolated source")
    original=SOURCE.read_bytes()
    if sha(original)!=OLD_SHA:
        raise ValueError("Original source fingerprint mismatch")
    if LAB.exists() or LAB.is_symlink():
        raise ValueError("Lab already exists; do not overwrite")
    changed=original+MARKER
    archive_file=LAB/NAME
    # Byte-level distinct payload, same single permitted ZIP entry
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        z.writestr("Contents/Resources/manager.py", changed)
    archive=buffer.getvalue()
    payload={
        "schema":1,"channel":"manager-stable","product":"Rap Brain Manager",
        "version":"1.0.6","install_allowed":False,
        "archive":{
            "filename":NAME,"size":len(archive),"sha256":sha(archive),
            "url":"https://github.com/albanherisson/rap-brain-updates/releases/download/lab-1.0.6/"+NAME
        }
    }
    canonical=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    LAB.mkdir(mode=0o700)
    try:
        archive_file.write_bytes(archive)
        (LAB/"canonical_payload.json").write_bytes(canonical)
        (LAB/"unsigned_payload.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
        (LAB/"README.txt").write_text(
            "DISPOSABLE LAB ONLY. install_allowed=false. No code installed.\n"
            "No private key was read. This is not a production release.\n"
        )
    except Exception:
        for item in LAB.iterdir():item.unlink()
        LAB.rmdir()
        raise
    print("OK: distinct unsigned payload prepared")
    print("OK: old and new file hashes differ:", sha(original)!=sha(changed))
    print("OK: installation prohibited, no signing key accessed")
    print("ZIP SHA256:",sha(archive))
    print("Canonical payload:", LAB/"canonical_payload.json")
    print("No Manager application or Rap Brain data modified")

if __name__=="__main__":
    try:main()
    except (OSError,ValueError) as e:
        print("REFUS:",str(e),file=sys.stderr)
        sys.exit(1)
