#!/usr/bin/env python3
"""Pinned, read-only Manager AST path provenance review.

Prints static source line numbers and *categories*, never values, paths,
credentials or source snippets. This is triage, NOT proof of safe isolation.
"""
import ast,hashlib,stat
from pathlib import Path
FILE=Path.home()/"Applications/Rap Brain Manager.app/Contents/Resources/manager.py"
PIN="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
SINKS={"open","write_text","write_bytes","mkdir","rename","replace","unlink",
       "rmtree","copytree","Popen","run","call","check_call","check_output"}
def summarize(source):
 tree=ast.parse(source.decode("utf-8"))
 assignments={}
 for n in ast.walk(tree):
  if isinstance(n,(ast.Assign,ast.AnnAssign)):
   v=n.value
   if v is None:continue
   targets=n.targets if isinstance(n,ast.Assign) else [n.target]
   for target in targets:
    if isinstance(target,ast.Name):assignments.setdefault(target.id,[]).append(v)
 def provenance(node,depth=0,seen=frozenset()):
  if depth>5:return "unknown"
  if isinstance(node,ast.Constant):
   return "absolute_literal" if isinstance(node.value,str) and node.value.startswith("/") else "literal"
  if isinstance(node,ast.Name):
   if node.id in seen:return "cycle"
   values=assignments.get(node.id,[])
   if len(values)!=1:return "variable_unresolved"
   return provenance(values[0],depth+1,seen|{node.id})
  if isinstance(node,ast.Call):
   f=node.func
   if isinstance(f,ast.Attribute) and f.attr=="home":return "home_call"
   if isinstance(f,ast.Name) and f.id in ("Path","str"):return "constructor_"+(provenance(node.args[0],depth+1,seen) if node.args else "empty")
   return "call_unresolved"
  if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div):return "joined_"+provenance(node.left,depth+1,seen)
  if isinstance(node,ast.Attribute):return "attribute_unresolved"
  return "expression_unresolved"
 entries=[]
 for node in ast.walk(tree):
  if not isinstance(node,ast.Call):continue
  f=node.func
  name=f.id if isinstance(f,ast.Name) else f.attr if isinstance(f,ast.Attribute) else ""
  if name not in SINKS:continue
  arg=node.args[0] if node.args else f.value if isinstance(f,ast.Attribute) else None
  category=provenance(arg) if arg is not None else "unknown"
  details=""
  if name=="Popen":
   args={k.arg for k in node.keywords}
   details="env="+str("env" in args)+",cwd="+str("cwd" in args)
  entries.append((node.lineno,name,category,details))
 return sorted(entries)
def main():
 if FILE.is_symlink():raise SystemExit("REFUS: symlink")
 meta=FILE.lstat()
 if not stat.S_ISREG(meta.st_mode) or not 0<meta.st_size<=100000:raise SystemExit("REFUS: metadata")
 data=FILE.read_bytes()
 if hashlib.sha256(data).hexdigest()!=PIN:raise SystemExit("REFUS: fingerprint")
 print("MANAGER PATH PROVENANCE — STATIC READ ONLY")
 for line,name,category,details in summarize(data):
  print(f"L{line}: {name} [{category}] {details}".rstrip())
 print("NOT a proof of isolation; no code launched; no path values printed")
if __name__=="__main__":main()
