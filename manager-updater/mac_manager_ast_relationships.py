#!/usr/bin/env python3
"""Pinned read-only AST relationship audit: no source text or literals emitted."""
import ast
import hashlib
import stat
from pathlib import Path

APP=Path.home()/"Applications/Rap Brain Manager.app"
FILE=APP/"Contents/Resources/manager.py"
SHA="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"

def report(source):
    root=ast.parse(source)
    parents={}
    for p in ast.walk(root):
        for child in ast.iter_child_nodes(p):parents[child]=p
    results=[]
    for node in ast.walk(root):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute):continue
        name=node.func.attr
        if name not in {"kill","serve_forever","ThreadingHTTPServer","shutdown"}:continue
        enclosing=None
        cur=node
        while cur in parents:
            cur=parents[cur]
            if isinstance(cur,(ast.FunctionDef,ast.AsyncFunctionDef)):
                enclosing=cur;break
        local_calls=set()
        if enclosing:
            for child in ast.walk(enclosing):
                if isinstance(child,ast.Call):
                    f=child.func
                    local_calls.add(f.attr if isinstance(f,ast.Attribute) else f.id if isinstance(f,ast.Name) else "?")
        receiver=node.func.value
        receiver_type=type(receiver).__name__
        direct_parent=type(parents.get(node)).__name__
        results.append((name,node.lineno,receiver_type,direct_parent,
                        "Popen" in local_calls,"wait" in local_calls,
                        "poll" in local_calls,"shutdown" in local_calls))
    return sorted(results,key=lambda x:x[1])

def main():
    if APP.is_symlink() or FILE.is_symlink():raise SystemExit("REFUS: symlink")
    st=FILE.lstat()
    if not stat.S_ISREG(st.st_mode) or not (0<st.st_size<=100000):raise SystemExit("REFUS: file")
    raw=FILE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise SystemExit("REFUS: changed SHA")
    print("RAPBRAIN AST RELATIONSHIPS — PINNED SOURCE — READ ONLY")
    for name,lineno,receiver,parent,spawn,wait,poll,stop in report(raw.decode("utf-8")):
        print(f"line={lineno} call={name} receiver_ast={receiver} parent_ast={parent} "
              f"function_has_Popen={spawn} wait={wait} poll={poll} shutdown={stop}")
    print("No executable Manager code run; no source or secrets displayed")
if __name__=="__main__":main()
