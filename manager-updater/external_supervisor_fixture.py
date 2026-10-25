"""Disposable external updater experiment. NEVER accepts an actual .app."""
import fcntl,hashlib,json,os,stat,tempfile
from pathlib import Path
MARKER=b'RAPBRAIN_DISPOSABLE_SUPERVISOR_V2\n'
def digest(b):return hashlib.sha256(b).hexdigest()
def read(p):
 s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_size>2000000:raise ValueError("Unsafe test file")
 return p.read_bytes()
def write(p,data):
 fd,temp=tempfile.mkstemp(dir=p.parent,prefix=".stage-")
 try:
  with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(temp,p)
 finally:
  if os.path.exists(temp):os.unlink(temp)
def run(root,health=True,crash=None):
 root=Path(root).absolute()
 if root.name!="DisposableSupervisorFixture" or not root.is_dir() or root.is_symlink():
  raise ValueError("Fixture-only; refuses real Manager")
 if read(root/"fixture.marker")!=MARKER:raise ValueError("Missing fixture marker")
 for name in ("manager.txt","candidate.txt"):read(root/name)
 for name in ("backup.txt","journal.json","transaction.lock"):
  if (root/name).is_symlink():raise ValueError("Symlink refused")
 fd=os.open(root/"transaction.lock",os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  live=root/"manager.txt";backup=root/"backup.txt";state=root/"journal.json"
  if state.exists():
   j=json.loads(read(state))
   if type(j) is not dict or set(j)!={"phase","old_sha","new_sha"}:raise ValueError("Bad journal")
   if j["phase"] in ("prepared","switched"):
    old=read(backup)
    if digest(old)!=j["old_sha"]:raise ValueError("Corrupt backup; refusing recovery")
    write(live,old);j["phase"]="rolled_back";write(state,json.dumps(j).encode())
    return "RECOVERED_OLD"
   if j["phase"] in ("committed","rolled_back"):return j["phase"].upper()
   raise ValueError("Unexpected phase")
  old,new=read(live),read(root/"candidate.txt")
  if old==new:raise ValueError("Identical fixture")
  if backup.exists():raise ValueError("Unexpected backup")
  write(backup,old)
  j={"phase":"prepared","old_sha":digest(old),"new_sha":digest(new)}
  write(state,json.dumps(j).encode())
  if crash=="prepared":raise RuntimeError("SIMULATED_INTERRUPTION_PREPARED")
  write(live,new);j["phase"]="switched";write(state,json.dumps(j).encode())
  if crash=="switched":raise RuntimeError("SIMULATED_INTERRUPTION_SWITCHED")
  if not health:
   write(live,old);j["phase"]="rolled_back";write(state,json.dumps(j).encode())
   return "ROLLED_BACK"
  j["phase"]="committed";write(state,json.dumps(j).encode())
  return "COMMITTED"
 finally:os.close(fd)
