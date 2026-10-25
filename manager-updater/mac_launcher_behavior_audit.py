#!/usr/bin/env python3
"""Read-only behavioral summary of the known installed Mac launcher.
Does not print script contents, paths to secrets, tokens, env variables or literal strings.
Does not start/stop processes, open browsers or modify files.
"""
import ast
import hashlib
from pathlib import Path
import stat

APP=Path.home()/"Applications/Rap Brain Manager.app"
LAUNCHER=APP/"Contents/Resources/launcher.py"
EXPECTED="c6045467cff38f8a6f7a73129c333fbf0a9b37e0cd8cb080cc6ee3336126543e"

def report_from_source(source):
    tree=ast.parse(source)
    calls={}
    for node in ast.walk(tree):
        if isinstance(node,ast.Call):
            fn=node.func
            name=fn.id if isinstance(fn,ast.Name) else fn.attr if isinstance(fn,ast.Attribute) else None
            if name:calls[name]=calls.get(name,0)+1
    return {
        "popen":calls.get("Popen",0),
        "subprocess_run":calls.get("run",0),
        "signals_kill":calls.get("kill",0),
        "signals_terminate":calls.get("terminate",0),
        "loopback_probe":calls.get("urlopen",0),
        "opening_browser":calls.get("open",0),
        "process_poll":calls.get("poll",0),
        "sleep_calls":calls.get("sleep",0),
        "os_replace":calls.get("replace",0),
        "pid_wait":calls.get("wait",0),
        "has_entrypoint":any(isinstance(n,ast.If) and isinstance(n.test,ast.Compare) for n in tree.body),
    }

def main():
    if APP.is_symlink() or LAUNCHER.is_symlink():raise SystemExit("REFUS: symbolic link")
    info=LAUNCHER.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>30000:
        raise SystemExit("REFUS: launcher differs in format")
    raw=LAUNCHER.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=EXPECTED:
        raise SystemExit("REFUS: launcher differs from version previously inspected")
    findings=report_from_source(raw.decode("utf-8"))
    print("LANCEUR RECONNU / COMPORTEMENT OBSERVABLE (SANS EXECUTION)")
    for name,value in sorted(findings.items()):
        print(f"{name}: {value}")
    print("LECTURE SEULE — aucun contenu, jeton ou clé révélé")
if __name__=="__main__":main()
