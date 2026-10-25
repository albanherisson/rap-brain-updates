#!/usr/bin/env python3
"""Read-only originals; disposable full-bundle apply / rollback for a DISTINCT signed lab ZIP.
Does not launch apps, access signing keys, publish or install an update.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

HOME=Path.home()
ROOT=HOME/"Library/Application Support/RapBrainManager/isolated-dryrun"
SOURCE=ROOT/"Rap Brain Manager - Isolated Copy.app"
APP=HOME/"Applications/Rap Brain Manager.app"
LAB=ROOT/"distinct-unsigned-lab-1.0.6"
NAME="Rap_Brain_Manager_1.0.6_lab_distinct.zip"
REL="Contents/Resources/manager.py"
OLD_SHA="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
INFO_SHA="4475f3c50dfe7e0748a13158904798bfeddedd5c151ffcff43ac29027a3b4784"
MARK=b"\n# RAP_BRAIN_DISTINCT_UNSIGNED_LAB_ONLY\n"
TRUSTED_PUBKEY="LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY="
SWIFT='''import Foundation
import CryptoKit
let args=CommandLine.arguments
guard args.count==3,let pub=Data(base64Encoded:"LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY="),
      let key=try? Curve25519.Signing.PublicKey(rawRepresentation:pub),
      let sig=Data(base64Encoded:args[1]),sig.count==64,
      let bytes=try? Data(contentsOf:URL(fileURLWithPath:args[2])) else { exit(2) }
guard key.isValidSignature(sig,for:bytes) else {exit(3)}
print("VALID")
'''
def sha(data):return hashlib.sha256(data).hexdigest()
def read_regular(path,maxbytes):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>maxbytes:raise ValueError("Unsafe file: "+str(path))
    return path.read_bytes()
def inventory(root):
    if not root.is_dir() or root.is_symlink():raise ValueError("Unsafe app bundle")
    records={};total=0
    for base,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            p=Path(base)/name;s=p.lstat()
            if not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):
                raise ValueError("Bundle symlink/special file refused")
            if stat.S_ISREG(s.st_mode):
                total+=s.st_size
                if total>100_000_000:raise ValueError("App too large")
                records[str(p.relative_to(root))]=(s.st_size,sha(p.read_bytes()),stat.S_IMODE(s.st_mode))
    return records
def main():
    if ROOT.is_symlink() or not ROOT.is_dir() or LAB.is_symlink() or not LAB.is_dir():
        raise ValueError("Missing isolated test files")
    before=inventory(SOURCE)
    if before[REL][1]!=OLD_SHA or before["Contents/Info.plist"][1]!=INFO_SHA:
        raise ValueError("Isolated copy no longer matches known safe state")
    app_before=(sha(read_regular(APP/REL,2_000_000)),sha(read_regular(APP/"Contents/Info.plist",20000)))
    if app_before!=(OLD_SHA,INFO_SHA):raise ValueError("Installed Manager changed")
    catalog=json.loads(read_regular(LAB/"catalog.json",65536))
    payload=catalog["payload"]
    if not isinstance(payload,dict) or payload.get("schema")!=1 or payload.get("channel")!="manager-stable" or payload.get("product")!="Rap Brain Manager" or payload.get("version")!="1.0.6" or payload.get("install_allowed") is not False:
        raise ValueError("Unexpected catalog fields")
    entry=payload["archive"]
    if entry.get("filename")!=NAME:raise ValueError("Wrong archive name")
    archive=read_regular(LAB/NAME,250_000_000)
    if len(archive)!=entry["size"] or sha(archive)!=entry["sha256"]:
        raise ValueError("Archive digest mismatch")
    canonical=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()
    with tempfile.TemporaryDirectory(prefix="rapbrain-verified-distinct-") as tmp:
        temp=Path(tmp)
        path=temp/"canonical.json";path.write_bytes(canonical)
        verifier=temp/"verify.swift";verifier.write_text(SWIFT)
        result=subprocess.run(["/usr/bin/swift",str(verifier),catalog["signature"],str(path)],capture_output=True,text=True,timeout=120)
        if result.returncode or result.stdout.strip()!="VALID":raise ValueError("Pinned CryptoKit verification failed")
        print("OK: signature réelle du fichier modifié vérifiée par CryptoKit")
        with zipfile.ZipFile(LAB/NAME) as z:
            if z.namelist()!=[REL]:raise ValueError("ZIP contains unexpected entries")
            info=z.getinfo(REL)
            if info.file_size>2_000_000 or info.flag_bits&1:raise ValueError("Unsafe ZIP entry")
            incoming=z.read(REL)
        if sha(incoming)==OLD_SHA or incoming!=read_regular(SOURCE/REL,2_000_000)+MARK:
            raise ValueError("Not an expected distinct lab payload")
        copy=temp/"Disposable Manager.app"
        shutil.copytree(SOURCE,copy,symlinks=True,copy_function=shutil.copy2)
        if inventory(copy)!=before:raise ValueError("Disposable copy differs")
        target=copy/REL;original=target.read_bytes();mode=stat.S_IMODE(target.stat().st_mode)
        stage=target.with_name("manager.stage");stage.write_bytes(incoming);stage.chmod(mode);os.replace(stage,target)
        if sha(target.read_bytes())!=sha(incoming):raise ValueError("Stage mismatch")
        print("OK: version réellement différente appliquée à une copie jetable")
        # Health failure injection forces rollback, no app is launched.
        rollback=target.with_name("manager.restore");rollback.write_bytes(original);rollback.chmod(mode);os.replace(rollback,target)
        if inventory(copy)!=before:raise ValueError("Full-bundle rollback mismatch")
        print("OK: échec simulé, restauration intégrale de",len(before),"fichiers")
    if inventory(SOURCE)!=before or (sha(read_regular(APP/REL,2_000_000)),sha(read_regular(APP/"Contents/Info.plist",20000)))!=app_before:
        raise ValueError("Original bundle changed")
    print("OK: Manager installé, copie isolée, icône et données Rap Brain intacts")
    print("LAB ONLY: aucune application lancée ou mise à jour installée")
if __name__=="__main__":
    try:main()
    except Exception as exc:print("REFUS:",str(exc),file=sys.stderr);sys.exit(1)
