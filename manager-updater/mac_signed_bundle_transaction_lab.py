#!/usr/bin/env python3
"""Signed ZIP + disposable full-bundle transaction drill. No installation or app launch."""
import hashlib, os, shutil, stat, subprocess, sys, tempfile
from pathlib import Path
from urllib.request import urlopen
ROOT=Path.home()/"Library/Application Support/RapBrainManager/isolated-dryrun"
SRC=ROOT/"Rap Brain Manager - Isolated Copy.app"
APP=Path.home()/"Applications/Rap Brain Manager.app"
CAND=ROOT/"publisher-signed-candidate-1.0.6"
REL="Contents/Resources/manager.py"
MAIN="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
INFO="4475f3c50dfe7e0748a13158904798bfeddedd5c151ffcff43ac29027a3b4784"
ZIP="6f9225d9bb4c12fb200c9bc0074240bf80cbe48648db8a6049d018eddaebc9b7"
VERIFY_URL="https://raw.githubusercontent.com/albanherisson/rap-brain-updates/8652ec46a7a98724e5896a1163661720829e8cb1/manager-updater/mac_verify_signed_candidate.py"
# This known-good public verifier is fetched from immutable revision. The signer public key is pinned within it.

def fail(s): raise ValueError(s)
def sha(b):return hashlib.sha256(b).hexdigest()
def read(p,cap):
 st=p.lstat()
 if not stat.S_ISREG(st.st_mode) or st.st_size>cap:fail("Unsafe file "+str(p))
 return p.read_bytes()
def snapshot(root):
 if not root.is_dir() or root.is_symlink():fail("Unsafe directory")
 out={};total=0
 for parent,dirs,files in os.walk(root,followlinks=False):
  for name in dirs+files:
   path=Path(parent)/name; s=path.lstat()
   if not(stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):fail("Links and special files prohibited")
   if stat.S_ISREG(s.st_mode):
    total+=s.st_size
    if total>100*1024*1024:fail("Bundle exceeds safe size")
    out[str(path.relative_to(root))]=(s.st_size,sha(path.read_bytes()),stat.S_IMODE(s.st_mode))
 return out
def run():
 if not ROOT.is_dir() or ROOT.is_symlink() or SRC.resolve()==APP.resolve():fail("Invalid isolated location")
 baseline=snapshot(SRC)
 if baseline[REL][1]!=MAIN or baseline["Contents/Info.plist"][1]!=INFO:fail("Source fingerprint changed")
 app_before=(sha(read(APP/REL,2_000_000)),sha(read(APP/"Contents/Info.plist",100000)))
 if app_before!=(MAIN,INFO):fail("Installed Manager changed since inventory")
 if CAND.is_symlink() or not CAND.is_dir():fail("Signed candidate missing")
 # The read-only verifier uses Apple CryptoKit, checks the signed catalog, expected ZIP SHA,
 # ZIP content and refuses a tampered signature. Do not execute code from the ZIP.
 with tempfile.TemporaryDirectory(prefix="rapbrain-verify-") as td:
  verifier=Path(td)/"verifier.py"
  with urlopen(VERIFY_URL,timeout=15) as response:
   if response.geturl()!=VERIFY_URL:fail("Verifier redirect refused")
   code=response.read(40000)
  if not code or len(code)>=40000:fail("Verifier download invalid")
  verifier.write_bytes(code)
  res=subprocess.run([sys.executable,str(verifier)],capture_output=True,text=True,timeout=180)
  if res.returncode or "OK: signature réelle du catalogue vérifiée avec CryptoKit" not in res.stdout:
   fail("CryptoKit verifier failed: "+(res.stderr or res.stdout)[:250])
 archive=CAND/"Rap_Brain_Manager_1.0.6.zip"
 if sha(read(archive,250*1024*1024))!=ZIP:fail("Archive changed after verification")
 import zipfile
 with zipfile.ZipFile(archive) as z:
  if z.namelist()!=[REL]:fail("Unexpected ZIP structure")
  incoming=z.read(REL)
 if sha(incoming)!=MAIN:fail("Unexpected payload")
 print("OK: archive réelle signée et vérifiée avec CryptoKit")
 with tempfile.TemporaryDirectory(prefix="rapbrain-signed-test-") as td:
  copy=Path(td)/"Disposable Manager.app"
  shutil.copytree(SRC,copy,symlinks=True,copy_function=shutil.copy2)
  if snapshot(copy)!=baseline:fail("Initial copy differs")
  target=copy/REL; old=target.read_bytes(); mode=stat.S_IMODE(target.stat().st_mode)
  stage=target.with_name("manager.py.new")
  stage.write_bytes(incoming);stage.chmod(mode);os.replace(stage,target)
  print("OK: fichier signé appliqué à une copie jetable uniquement")
  # Inject failing health result and restore the old file.
  rollback=target.with_name("manager.py.restore")
  rollback.write_bytes(old);rollback.chmod(mode);os.replace(rollback,target)
  if snapshot(copy)!=baseline:fail("Rollback differs from full-bundle baseline")
  print("OK: panne simulée, restauration complète de",len(baseline),"fichiers")
 if snapshot(SRC)!=baseline or (sha(read(APP/REL,2_000_000)),sha(read(APP/"Contents/Info.plist",100000)))!=app_before:
  fail("Original Manager or isolated source changed")
 print("OK: Manager installé, copie isolée et données Rap Brain non modifiés")
 print("LAB ONLY: signed ZIP currently carries the SAME manager.py bytes; not a production update")
if __name__=="__main__":
 try:run()
 except Exception as e:print("REFUS:",e,file=sys.stderr);sys.exit(1)
