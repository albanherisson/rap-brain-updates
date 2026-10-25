#!/usr/bin/env python3
"""Read-only offline audit of installed Manager filesystem access surface.

Pinned SHA check, AST parsing only. Outputs counts/operation names, NOT file
paths, literals, keys, or source lines. Never executes Manager code or changes files.
"""
import ast,hashlib,stat
from pathlib import Path
APP=Path.home()/"Applications/Rap Brain Manager.app"
FILE=APP/"Contents/Resources/manager.py"
SHA="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
WATCH={"open","read_text","read_bytes","write_text","write_bytes","mkdir",
       "unlink","replace","rename","rmtree","copytree","getenv","environ",
       "expanduser","home","sqlite3","connect","chdir","Popen"}
def inspect(raw):
 tree=ast.parse(raw.decode("utf-8"))
 calls={name:0 for name in WATCH}
 for node in ast.walk(tree):
  if not isinstance(node,ast.Call):continue
  f=node.func
  name=f.id if isinstance(f,ast.Name) else f.attr if isinstance(f,ast.Attribute) else ""
  if name in calls:calls[name]+=1
 return calls
def main():
 if APP.is_symlink() or FILE.is_symlink():raise SystemExit("REFUS: symlink")
 st=FILE.lstat()
 if not stat.S_ISREG(st.st_mode) or not 0<st.st_size<=100000:raise SystemExit("REFUS: file metadata")
 raw=FILE.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=SHA:raise SystemExit("REFUS: changed file")
 print("ISOLATION READINESS AUDIT - VERIFIED SOURCE - READ ONLY")
 for name,count in sorted(inspect(raw).items()):
  if count:print(f"{name}: {count}")
 print("No Manager code executed. No paths or source literals exposed.")
if __name__=="__main__":main()
