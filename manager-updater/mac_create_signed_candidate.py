#!/usr/bin/env python3
"""Build a NON-INSTALLABLE publisher-signed candidate from the verified isolated copy.
Does NOT launch/modify either app, and does NOT upload or install anything.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

HOME = Path.home()
ROOT = HOME / "Library/Application Support/RapBrainManager/isolated-dryrun"
COPY = ROOT / "Rap Brain Manager - Isolated Copy.app"
OUT = ROOT / "publisher-signed-candidate-1.0.6"
SIGNER = HOME / "Applications/Rap Brain Manager.app/Contents/Resources/publisher_key.swift"
KEY_FILE = HOME / "Library/Application Support/RapBrainManager/publisher_ed25519.key"
EXPECTED_MANAGER = "bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
EXPECTED_SIGNER = "a661d2795eb11fb73221597bd6157ea520502cfbfd622392fcdea10ebfdae243"
PUBKEY = "LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY="
NAME = "Rap_Brain_Manager_1.0.6.zip"
VERSION = "1.0.6"

def sha(b): return hashlib.sha256(b).hexdigest()
def refuse(reason): raise ValueError(reason)
def regular(path, cap):
    st=path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
        refuse("Unsafe path or oversized file: " + str(path))
    return path.read_bytes()

def main():
    if not ROOT.is_dir() or ROOT.is_symlink() or not COPY.is_dir() or COPY.is_symlink():
        refuse("Verified isolated copy is missing")
    if OUT.exists() or OUT.is_symlink():
        refuse("Candidate already exists; refusing to overwrite")
    manager = regular(COPY / "Contents/Resources/manager.py", 2_000_000)
    signer = regular(SIGNER, 50_000)
    if sha(manager)!=EXPECTED_MANAGER or sha(signer)!=EXPECTED_SIGNER:
        refuse("Installed source fingerprint differs from previously verified inventory")
    key_stat=KEY_FILE.lstat()
    if not stat.S_ISREG(key_stat.st_mode) or (stat.S_IMODE(key_stat.st_mode) & 0o077):
        refuse("Private signing key is missing or insecurely permissioned")
    OUT.mkdir(mode=0o700)
    try:
        archive=OUT/NAME
        with zipfile.ZipFile(archive,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            z.writestr("Contents/Resources/manager.py",manager)
        archive_bytes=archive.read_bytes()
        payload={"schema":1,"channel":"manager-stable","product":"Rap Brain Manager",
                 "version":VERSION,"install_allowed":False,"archive":{
                 "filename":NAME,"size":len(archive_bytes),"sha256":sha(archive_bytes),
                 "url":"https://github.com/albanherisson/rap-brain-updates/releases/download/lab-1.0.6/"+NAME}}
        canonical=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()
        signing_data=OUT/"canonical_payload.json"
        signing_data.write_bytes(canonical)
        # Trusted, local Swift file: no remotely supplied code.
        signed=subprocess.run(["/usr/bin/swift",str(SIGNER),"sign",str(signing_data)],
             capture_output=True,text=True,check=True,timeout=120)
        signature=signed.stdout.strip()
        if len(base64.b64decode(signature,validate=True))!=64: refuse("Signing result malformed")
        (OUT/"catalog.json").write_text(json.dumps({"payload":payload,"signature":signature},indent=2,ensure_ascii=False)+"\n")
        (OUT/"public_key.txt").write_text(PUBKEY+"\n")
        # Signature is not the private key and may be shared.
        print("SUCCES: archive de test produite et signée par la clé locale")
        print("SUCCES: install_allowed=false; aucun changement dans le Manager")
        print("Archive SHA256:",sha(archive_bytes))
        print("Catalogue:",OUT/"catalog.json")
        print("Aucune publication, installation ni exécution effectuée.")
    except Exception:
        # Remove only the new directory created by this program.
        for child in OUT.iterdir(): child.unlink()
        OUT.rmdir()
        raise

if __name__=="__main__":
    try: main()
    except Exception as e:
        print("ECHEC:",e,file=sys.stderr)
        raise SystemExit(1)
