#!/usr/bin/env python3
"""Read-only pinned AST check of kill receivers and Popen variable assignments.
Never prints source strings, tokens or program arguments. No Manager code execution.
"""
import ast,hashlib,stat
from pathlib import Path
APP=Path.home()/"Applications/Rap Brain Manager.app"
FILE=APP/"Contents/Resources/manager.py"
SHA="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
def examine(src):
 tree=ast.parse(src); parents={}
 for p in ast.walk(tree):
  for child in ast.iter_child_nodes(p):parents[child]=p
 result=[]
 for n in ast.walk(tree):
  if not isinstance(n,ast.Call) or not isinstance(n.func,ast.Attribute) or n.func.attr!="kill":continue
  recv=n.func.value
  owner=n
  while owner in parents and not isinstance(owner,(ast.FunctionDef,ast.AsyncFunctionDef)):
   owner=parents[owner]
  if not isinstance(owner,(ast.FunctionDef,ast.AsyncFunctionDef)):
   result.append((n.lineno,"NO_FUNCTION","UNKNOWN",False,False));continue
  direct=recv.id if isinstance(recv,ast.Name) else None
  assignments=[]
  for x in ast.walk(owner):
   if isinstance(x,(ast.Assign,ast.AnnAssign)):
    val=x.value
    is_popen=isinstance(val,ast.Call) and ((isinstance(val.func,ast.Name) and val.func.id=="Popen") or (isinstance(val.func,ast.Attribute) and val.func.attr=="Popen"))
    targets=x.targets if isinstance(x,ast.Assign) else [x.target]
    if direct and any(isinstance(t,ast.Name) and t.id==direct for t in targets):
     assignments.append((x.lineno,is_popen))
  prior=[(line,popen) for line,popen in assignments if line<n.lineno]
  last=prior[-1] if prior else None
  result.append((n.lineno,"DIRECT_NAME" if direct else type(recv).__name__,"DIRECT_POPEN_ASSIGN" if last and last[1] else "UNPROVEN", bool(last),len(assignments)==1))
 return sorted(result)
def main():
 if APP.is_symlink() or FILE.is_symlink():raise SystemExit("REFUS: symlink")
 st=FILE.lstat()
 if not stat.S_ISREG(st.st_mode) or not 0<st.st_size<=100000:raise SystemExit("REFUS: file")
 raw=FILE.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=SHA:raise SystemExit("REFUS: changed SHA")
 print("MANAGER KILL RECEIVER AUDIT — READ ONLY")
 for line,kind,origin,has_assignment,single in examine(raw.decode("utf-8")):
  print(f"line={line} receiver={kind} nearest_assignment={origin} assignment_found={has_assignment} single_assignment={single}")
 print("Observational only; no PID signalling authorized")
if __name__=="__main__":main()
