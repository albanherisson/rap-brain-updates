#!/usr/bin/env python3
"""Read-only structural audit of installed launcher; emits no code, secrets or token values."""
import ast, hashlib
from pathlib import Path
import stat
APP=Path.home()/"Applications/Rap Brain Manager.app"
PATH=APP/"Contents/Resources/launcher.py"
BIN=APP/"Contents/MacOS/RapBrainManager"
EXPECTED="c6045467cff38f8a6f7a73129c333fbf0a9b37e0cd8cb080cc6ee3336126543e"
def main():
    if APP.is_symlink() or PATH.is_symlink() or BIN.is_symlink():raise SystemExit("REFUS: symbolic link")
    s=PATH.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_size>30000:raise SystemExit("REFUS: unsafe launcher")
    raw=PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=EXPECTED:raise SystemExit("REFUS: launcher differs from inspected version")
    tree=ast.parse(raw.decode("utf-8"))
    calls=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.Call):
            func=n.func
            if isinstance(func,ast.Name):calls.append(func.id)
            elif isinstance(func,ast.Attribute):calls.append(func.attr)
    names=set(calls)
    checks=["Popen","run","check_output","open","startfile","kill","terminate","send_signal","execv","execve","setsid","poll","wait","urlopen","urlretrieve","bind","listen","sleep","atexit"]
    print("LANCEUR INSTALLE — AUDIT STRUCTUREL EN LECTURE SEULE")
    print("Empreinte du lanceur Python: reconnue")
    print("Nombre de lignes:",len(raw.splitlines()))
    print("Points d'entrée Python:",", ".join(n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))) or "(aucun à la racine)")
    for key in checks:print(key+":", "PRESENT" if key in names else "absent")
    b=BIN.read_bytes() if BIN.is_file() and BIN.stat().st_size<=2000 else None
    print("Relais MacOS:","présent, petit script" if b is not None else "format inattendu")
    print("Aucun contenu de script, token ou clé affiché; aucune modification")
if __name__=="__main__":main()
