#!/usr/bin/env python3
"""Read-only, pinned-hash capability inventory of the installed Manager.

Never imports or executes Manager code, never opens an HTTP connection,
and never prints source lines, route strings, secrets, credentials or paths.
"""
import ast
import hashlib
import stat
from pathlib import Path

EXPECTED_SHA = "bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
MANAGER = Path.home() / "Applications/Rap Brain Manager.app/Contents/Resources/manager.py"
APP = Path.home() / "Applications/Rap Brain Manager.app"

def inventory(raw):
    tree = ast.parse(raw.decode("utf-8"))
    attrs = {}
    functions = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions += 1
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else "")
            if name in ("shutdown", "serve_forever", "HTTPServer", "ThreadingHTTPServer",
                        "signal", "kill", "terminate", "Popen", "run", "urlopen"):
                attrs[name] = attrs.get(name, 0) + 1
    return functions, attrs

def main():
    if APP.is_symlink() or MANAGER.is_symlink():
        raise SystemExit("REFUS: symbolic link")
    st = MANAGER.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size > 100000 or st.st_size < 1:
        raise SystemExit("REFUS: file metadata mismatch")
    raw = MANAGER.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA:
        raise SystemExit("REFUS: fingerprint mismatch; no inventory produced")
    functions, attrs = inventory(raw)
    print("RAP BRAIN MANAGER CAPABILITY INVENTORY — READ ONLY")
    print("SHA256: VERIFIED")
    print("Python functions:", functions)
    for key in sorted(("shutdown", "serve_forever", "HTTPServer",
                       "ThreadingHTTPServer", "signal", "kill",
                       "terminate", "Popen", "run", "urlopen")):
        print(key + ":", attrs.get(key, 0))
    print("No Manager code executed. No file modified.")

if __name__ == "__main__":
    main()
