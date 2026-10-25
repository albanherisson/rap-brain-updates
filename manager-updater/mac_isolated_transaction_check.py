#!/usr/bin/env python3
"""Replace/restore on a disposable third copy. Original and isolated source read-only."""
import hashlib, os, shutil, stat, sys, tempfile
from pathlib import Path

ROOT = Path.home() / "Library/Application Support/RapBrainManager/isolated-dryrun"
SOURCE = ROOT / "Rap Brain Manager - Isolated Copy.app"
INSTALLED = Path.home() / "Applications/Rap Brain Manager.app"
REL = Path("Contents/Resources/manager.py")
EXPECTED_MANAGER = "bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
EXPECTED_INFO = "4475f3c50dfe7e0748a13158904798bfeddedd5c151ffcff43ac29027a3b4784"

def sha(p):
    d=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1048576),b""): d.update(chunk)
    return d.hexdigest()

def snapshot(root):
    records={}
    total=0
    for base,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            p=Path(base)/name
            s=p.lstat()
            if stat.S_ISLNK(s.st_mode) or not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):
                raise ValueError("Symlink or special file refused")
            if stat.S_ISREG(s.st_mode):
                total += s.st_size
                if total > 100*1024*1024: raise ValueError("App too large")
                records[str(p.relative_to(root))]=(s.st_size,sha(p),stat.S_IMODE(s.st_mode))
    return records

def run():
    if not SOURCE.is_dir() or SOURCE.is_symlink() or not ROOT.is_dir() or ROOT.is_symlink():
        raise ValueError("Isolated source missing")
    if SOURCE.resolve()==INSTALLED.resolve(): raise ValueError("Unsafe source")
    if sha(SOURCE/REL)!=EXPECTED_MANAGER or sha(SOURCE/"Contents/Info.plist")!=EXPECTED_INFO:
        raise ValueError("Source fingerprint mismatch")
    before=snapshot(SOURCE)
    with tempfile.TemporaryDirectory(prefix="rapbrain-transaction-test-") as t:
        copy=Path(t)/"Disposable Test.app"
        shutil.copytree(SOURCE,copy,symlinks=True)
        if snapshot(copy)!=before: raise ValueError("Initial copy mismatch")
        target=copy/REL
        original=target.read_bytes()
        replacement=target.with_suffix(".new-test")
        marker=b"\n# RAP_BRAIN_DISPOSABLE_ROLLBACK_TEST_ONLY\n"
        try:
            replacement.write_bytes(original+marker)
            replacement.chmod(stat.S_IMODE(target.stat().st_mode))
            os.replace(replacement,target)
            if not target.read_bytes().endswith(marker): raise ValueError("Replacement failed")
            print("OK: remplacement du script dans la copie jetable")
            replacement.write_bytes(original)
            replacement.chmod(stat.S_IMODE(target.stat().st_mode))
            os.replace(replacement,target)
            if snapshot(copy)!=before: raise ValueError("Rollback differs from original")
            print("OK: restauration bit à bit de la copie jetable")
        finally:
            replacement.unlink(missing_ok=True)
    if snapshot(SOURCE)!=before: raise ValueError("Isolated source changed")
    if sha(INSTALLED/REL)!=EXPECTED_MANAGER: raise ValueError("Installed Manager fingerprint changed")
    print("OK: copie isolée inchangée; Manager installé inchangé")
    print("Aucune application lancée; aucune donnée Rap Brain touchée")

if __name__=="__main__":
    try: run()
    except (OSError,ValueError) as e:
        print("ECHEC:",str(e),file=sys.stderr)
        sys.exit(1)
