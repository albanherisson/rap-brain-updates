#!/usr/bin/env python3
"""Read-only pinned AST classification of subprocess launch and path risks."""
import ast,hashlib,stat
from pathlib import Path
APP=Path.home()/"Applications/Rap Brain Manager.app"
FILE=APP/"Contents/Resources/manager.py"
SHA="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
def classify(raw):
 tree=ast.parse(raw.decode())
 result={"popen_total":0,"explicit_env_keyword":0,"explicit_cwd_keyword":0,
         "shell_true_literal":0,"shell_unknown":0,"absolute_path_literals":0,
         "getenv_calls":0}
 for node in ast.walk(tree):
  if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value.startswith("/") and len(node.value)>1:
   result["absolute_path_literals"]+=1
  if not isinstance(node,ast.Call):continue
  f=node.func;name=f.attr if isinstance(f,ast.Attribute) else f.id if isinstance(f,ast.Name) else ""
  if name=="getenv":result["getenv_calls"]+=1
  if name!="Popen":continue
  result["popen_total"]+=1
  names={x.arg for x in node.keywords}
  if "env" in names:result["explicit_env_keyword"]+=1
  if "cwd" in names:result["explicit_cwd_keyword"]+=1
  for x in node.keywords:
   if x.arg=="shell":
    if isinstance(x.value,ast.Constant) and x.value.value is True:result["shell_true_literal"]+=1
    elif not isinstance(x.value,ast.Constant):result["shell_unknown"]+=1
 return result
def main():
 if APP.is_symlink() or FILE.is_symlink():raise SystemExit("REFUS: link")
 st=FILE.lstat()
 if not stat.S_ISREG(st.st_mode) or not 0<st.st_size<=100000:raise SystemExit("REFUS: file")
 raw=FILE.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=SHA:raise SystemExit("REFUS: changed fingerprint")
 print("RAPBRAIN SUBPROCESS ISOLATION — VERIFIED READ ONLY")
 for key,value in sorted(classify(raw).items()):print(f"{key}: {value}")
 print("No application executed or user paths revealed")
if __name__=="__main__":main()
