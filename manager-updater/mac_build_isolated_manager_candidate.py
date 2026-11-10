#!/usr/bin/env python3
"""Build a non-executable, disposable isolated Manager source candidate.

Reads verified installed source; AST rewrites Path.home() and each Popen call.
Never edits the original, installs, imports, executes or launches transformed code.
Popen replacement *always rejects* in this candidate until audited and enabled.
"""
import ast, hashlib, os, stat, tempfile
from pathlib import Path

PIN="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
TARGET=Path.home()/"Applications/Rap Brain Manager.app/Contents/Resources/manager.py"
INJECTION='''
def _rb_isolated_home():
    from pathlib import Path as _RBPath
    root = _RBPath(__file__).resolve().parent / "DISPOSABLE_DATA_DO_NOT_USE"
    # No real data directory is ever accessed by this non-executable candidate.
    return root

def _rb_disabled_popen(*args, **kwargs):
    raise RuntimeError("BLOCKED: isolated Manager process spawn not yet validated")
'''
class Transform(ast.NodeTransformer):
    def __init__(self): self.homes=0; self.popens=0
    def visit_Call(self,node):
        self.generic_visit(node)
        f=node.func
        if isinstance(f,ast.Attribute) and f.attr=="home" and isinstance(f.value,ast.Name) and f.value.id=="Path" and not node.args and not node.keywords:
            self.homes+=1
            return ast.copy_location(ast.Call(func=ast.Name(id="_rb_isolated_home",ctx=ast.Load()),args=[],keywords=[]),node)
        if (isinstance(f,ast.Name) and f.id=="Popen") or (isinstance(f,ast.Attribute) and f.attr=="Popen"):
            self.popens+=1
            node.func=ast.copy_location(ast.Name(id="_rb_disabled_popen",ctx=ast.Load()),f)
        return node

def transform(data):
    tree=ast.parse(data.decode("utf-8"),filename="manager.py")
    t=Transform()
    tree=t.visit(tree)
    assert t.homes==8 and t.popens==5,(t.homes,t.popens)
    ast.fix_missing_locations(tree)
    # Preserve module docstring and __future__ imports at their required positions.
    insert=0
    if tree.body and isinstance(tree.body[0],ast.Expr) and isinstance(tree.body[0].value,ast.Constant) and isinstance(tree.body[0].value.value,str):
        insert=1
    while insert<len(tree.body) and isinstance(tree.body[insert],ast.ImportFrom) and tree.body[insert].module=="__future__":
        insert+=1
    tree.body[insert:insert]=ast.parse(INJECTION).body
    ast.fix_missing_locations(tree)
    compile(tree,"isolated_manager_candidate.py","exec")
    return ast.unparse(tree).encode("utf-8"),t.homes,t.popens

def main():
    if TARGET.is_symlink():raise SystemExit("REFUS: original is symlink")
    st=TARGET.lstat()
    if not stat.S_ISREG(st.st_mode) or not 0<st.st_size<=100000:raise SystemExit("REFUS: invalid source metadata")
    original=TARGET.read_bytes()
    if hashlib.sha256(original).hexdigest()!=PIN:raise SystemExit("REFUS: original source fingerprint changed")
    patched,homes,popens=transform(original)
    with tempfile.TemporaryDirectory(prefix="rapbrain-manager-patch-preview-") as d:
        p=Path(d)/"isolated_manager_candidate.py"
        p.write_bytes(patched)
        assert p.read_bytes()==patched
        assert hashlib.sha256(TARGET.read_bytes()).hexdigest()==PIN
        print("OK: transformed isolated source successfully compiled (NOT EXECUTED)")
        print("OK: home references rewritten:",homes)
        print("OK: subprocess launches disabled:",popens)
        print("OK: candidate written only to disposable directory, then deleted")
    print("OK: installed Manager unchanged, no Rap Brain data accessed")
    print("BLOCKED: real launch remains prohibited until remaining filesystem paths reviewed")
if __name__=="__main__":main()
