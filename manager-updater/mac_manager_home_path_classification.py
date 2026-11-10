#!/usr/bin/env python3
"""Read-only AST classification of Manager home paths and subprocess calls.
No source strings, secret values, or absolute user paths are printed.
"""
import ast,hashlib,stat
from pathlib import Path
APP=Path.home()/"Applications/Rap Brain Manager.app"
FILE=APP/"Contents/Resources/manager.py"
SHA="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
WRITE={"mkdir","write_text","write_bytes","open","rename","replace","unlink","rmtree","copytree"}
def audit(raw):
 tree=ast.parse(raw.decode("utf-8"))
 out={"home_calls":0,"literal_home_children":0,"computed_home_paths":0,"subprocess_calls":0,"write_calls":0}
 for node in ast.walk(tree):
  if isinstance(node,ast.Call):
   f=node.func; name=f.attr if isinstance(f,ast.Attribute) else f.id if isinstance(f,ast.Name) else ""
   if name=="home":
    out["home_calls"]+=1
   if name=="Popen":out["subprocess_calls"]+=1
   if name in WRITE:out["write_calls"]+=1
  if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div) and isinstance(node.left,ast.Call):
   f=node.left.func
   if isinstance(f,ast.Attribute) and f.attr=="home":
    if isinstance(node.right,ast.Constant) and isinstance(node.right.value,str):
     out["literal_home_children"]+=1
    else:out["computed_home_paths"]+=1
 return out
def main():
 if APP.is_symlink() or FILE.is_symlink():raise SystemExit("REFUS: symlink")
 st=FILE.lstat()
 if not stat.S_ISREG(st.st_mode) or not 0<st.st_size<=100000:raise SystemExit("REFUS: file")
 raw=FILE.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=SHA:raise SystemExit("REFUS: SHA mismatch")
 print("RAP BRAIN ISOLATION CLASSIFICATION — READ ONLY")
 for name,count in sorted(audit(raw).items()):print(name+": "+str(count))
 print("NO application executed. HOME override is NOT approved by this audit.")
if __name__=="__main__":main()
