#!/usr/bin/env python3
"""Read-only control-flow analysis of the known launcher. No processes are signaled."""
import ast,hashlib,stat
from pathlib import Path
APP=Path.home()/"Applications/Rap Brain Manager.app"
FILE=APP/"Contents/Resources/launcher.py"
SHA="c6045467cff38f8a6f7a73129c333fbf0a9b37e0cd8cb080cc6ee3336126543e"
TARGETS={"Popen","kill","run","replace","urlopen","poll"}
def analyze(source):
 tree=ast.parse(source)
 classes={k:[] for k in TARGETS}
 parents={}
 for parent in ast.walk(tree):
  for child in ast.iter_child_nodes(parent):parents[child]=parent
 def owner(node):
  while node in parents:
   node=parents[node]
   if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):return "function"
   if isinstance(node,ast.If):return "conditional"
   if isinstance(node,(ast.For,ast.While)):return "loop"
  return "module"
 def context(node):
  found=set()
  while node in parents:
   node=parents[node]
   if isinstance(node,ast.Try):found.add("try")
   if isinstance(node,ast.ExceptHandler):found.add("except")
   if isinstance(node,ast.Finally):found.add("finally") # AST doesn't expose Finally node
   if isinstance(node,(ast.While,ast.For)):found.add("loop")
  return ",".join(sorted(found)) or "plain"
 for node in ast.walk(tree):
  if not isinstance(node,ast.Call):continue
  fn=node.func
  name=fn.id if isinstance(fn,ast.Name) else fn.attr if isinstance(fn,ast.Attribute) else None
  if name in TARGETS:
   classes[name].append((owner(node),context(node),len(node.args),len(node.keywords)))
 return classes
def main():
 if APP.is_symlink() or FILE.is_symlink():raise SystemExit("REFUS: symlink")
 st=FILE.lstat()
 if not stat.S_ISREG(st.st_mode) or st.st_size>30000:raise SystemExit("REFUS: unexpected file")
 raw=FILE.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=SHA:raise SystemExit("REFUS: launcher fingerprint differs")
 results=analyze(raw.decode("utf-8"))
 print("LANCEUR IDENTIFIE — ANALYSE DU CONTROLE DE FLUX (LECTURE SEULE)")
 for name,items in sorted(results.items()):
  print(name+": "+str(len(items)))
  for idx,(owner,context,args,kwargs) in enumerate(items,1):
   print("  invocation "+str(idx)+": "+owner+" / "+context+" / positional="+str(args)+" keyword="+str(kwargs))
 print("Aucune instruction lanceur exécutée; aucun PID, port, jeton ou donnée affiché")
if __name__=="__main__":main()
