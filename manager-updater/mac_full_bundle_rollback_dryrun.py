#!/usr/bin/env python3
"""Mac full-bundle dry-run ONLY. Never executes Manager, never reads Rap Brain data."""
import hashlib,os,shutil,stat,sys,tempfile
from pathlib import Path
ROOT=Path.home()/"Library/Application Support/RapBrainManager/isolated-dryrun"
SOURCE=ROOT/"Rap Brain Manager - Isolated Copy.app"
INSTALLED=Path.home()/"Applications/Rap Brain Manager.app"
REL="Contents/Resources/manager.py"
EXPECTED_MAIN="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
EXPECTED_INFO="4475f3c50dfe7e0748a13158904798bfeddedd5c151ffcff43ac29027a3b4784"

def sha(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1048576),b""):h.update(chunk)
 return h.hexdigest()
def inventory(root):
 if root.is_symlink() or not root.is_dir():raise ValueError("Unsafe bundle")
 result={};total=0
 for parent,dirs,names in os.walk(root,followlinks=False):
  for name in dirs+names:
   path=Path(parent)/name;mode=path.lstat().st_mode
   if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):raise ValueError("Symlink or special file refused")
   if stat.S_ISREG(mode):
    size=path.stat().st_size;total+=size
    if total>100*1024*1024:raise ValueError("Bundle exceeds safe limit")
    result[str(path.relative_to(root))]=(size,sha(path),stat.S_IMODE(mode))
 return result
def run():
 if ROOT.is_symlink() or not ROOT.is_dir() or SOURCE.resolve()==INSTALLED.resolve():
  raise ValueError("Invalid isolated root or source")
 baseline=inventory(SOURCE)
 if baseline[REL][1]!=EXPECTED_MAIN or baseline["Contents/Info.plist"][1]!=EXPECTED_INFO:
  raise ValueError("Isolated bundle changed since inventory")
 live=(sha(INSTALLED/REL),sha(INSTALLED/"Contents/Info.plist"))
 if live!=(EXPECTED_MAIN,EXPECTED_INFO):raise ValueError("Installed Manager changed since inventory")
 with tempfile.TemporaryDirectory(prefix="rapbrain-disposable-bundle-") as temp:
  disposable=Path(temp)/"Disposable Manager.app"
  shutil.copytree(SOURCE,disposable,symlinks=True,copy_function=shutil.copy2)
  if inventory(disposable)!=baseline:raise ValueError("Copy mismatch")
  target=disposable/REL;original=target.read_bytes();permissions=stat.S_IMODE(target.stat().st_mode)
  stage=target.with_name("manager.py.stage")
  stage.write_bytes(original+b"\n# DISPOSABLE_TEST_ONLY\n");stage.chmod(permissions)
  os.replace(stage,target)
  if not target.read_bytes().endswith(b"# DISPOSABLE_TEST_ONLY\n"):
   raise ValueError("Update drill failed")
  print("OK: simulated replacement only in disposable full app bundle")
  restore=target.with_name("manager.py.restore")
  restore.write_bytes(original);restore.chmod(permissions)
  os.replace(restore,target)
  if inventory(disposable)!=baseline:raise ValueError("Full-bundle rollback mismatch")
  print("OK: full-bundle rollback restored "+str(len(baseline))+" files")
 if inventory(SOURCE)!=baseline:raise ValueError("Isolated source changed")
 if (sha(INSTALLED/REL),sha(INSTALLED/"Contents/Info.plist"))!=live:
  raise ValueError("Installed Manager changed")
 print("OK: installed Manager and isolated source unchanged")
 print("OK: no application launched, no Rap Brain data accessed")
if __name__=="__main__":
 try:run()
 except (ValueError,OSError,KeyError) as e:
  print("REFUS:",e,file=sys.stderr);sys.exit(1)
