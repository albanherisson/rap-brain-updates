#!/usr/bin/env python3
"""Read-only, fingerprint-pinned AST audit of process stops and HTTP server lifecycle.

Does not execute imported Manager source, print literal strings, signal processes,
open sockets, or change installed files.
"""
import ast
import hashlib
import stat
from pathlib import Path

EXPECTED = "bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
APP = Path.home() / "Applications/Rap Brain Manager.app"
SOURCE = APP / "Contents/Resources/manager.py"
NAMES = {"kill", "Popen", "serve_forever", "shutdown", "ThreadingHTTPServer"}

def summary(code):
    tree = ast.parse(code)
    parents = {}
    for p in ast.walk(tree):
        for child in ast.iter_child_nodes(p):
            parents[child] = p
    lines = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        if name not in NAMES:
            continue
        chain = []
        p = n
        while p in parents:
            p = parents[p]
            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chain.append("function")
            elif isinstance(p, ast.Try):
                chain.append("try")
            elif isinstance(p, ast.ExceptHandler):
                chain.append("except")
            elif isinstance(p, ast.If):
                chain.append("if")
        lines.append((name, n.lineno, ",".join(chain) or "module",
                      len(n.args), len(n.keywords)))
    return sorted(lines, key=lambda row: row[1])

def main():
    if APP.is_symlink() or SOURCE.is_symlink():
        raise SystemExit("REFUS: symlink")
    metadata = SOURCE.lstat()
    if not stat.S_ISREG(metadata.st_mode) or not (0 < metadata.st_size <= 100000):
        raise SystemExit("REFUS: unexpected file")
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != EXPECTED:
        raise SystemExit("REFUS: fingerprint mismatch")
    print("MANAGER CONTROL-FLOW AUDIT — READ ONLY, VERIFIED SHA")
    for name, line, contexts, args, kwargs in summary(data.decode("utf-8")):
        print(f"line={line} call={name} context={contexts} args={args} keywords={kwargs}")
    print("No code executed or file modified; no source strings printed")

if __name__ == "__main__":
    main()
