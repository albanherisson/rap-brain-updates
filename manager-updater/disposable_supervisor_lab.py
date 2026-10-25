#!/usr/bin/env python3
"""Disposable external supervisor lab ONLY. Refuses actual app paths."""
import argparse, hashlib, json, os, pathlib, tempfile
MARKER="RAPBRAIN_DISPOSABLE_SUPERVISOR_FIXTURE_V1"
def sha(data):return hashlib.sha256(data).hexdigest()
def atomic(p,data):
    fd,t=tempfile.mkstemp(prefix=".stage-",dir=p.parent)
    try:
        with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(t,p)
    finally:
        if os.path.exists(t):os.unlink(t)
def check(root):
    root=pathlib.Path(root).expanduser().absolute()
    if root.name!="DisposableSupervisorFixture" or not root.is_dir() or root.is_symlink():raise ValueError("Not a disposable fixture")
    marker=root/"fixture.marker"
    if marker.is_symlink() or marker.read_text()!=MARKER:raise ValueError("Missing fixture marker")
    for name in ("manager.txt","candidate.txt"):
        p=root/name
        if not p.is_file() or p.is_symlink() or p.stat().st_size>1024*1024:raise ValueError("Unsafe fixture file")
    for name in ("backup.txt","state.json"):
        if (root/name).is_symlink():raise ValueError("Symlink refused")
    return root
def run(root,health=True,crash=None):
    root=check(root)
    live,candidate,backup,state=[root/n for n in ("manager.txt","candidate.txt","backup.txt","state.json")]
    if state.exists():
        existing=json.loads(state.read_text())
        if existing.get("stage") not in ("prepared","switched","committed","rolled_back"):raise ValueError("Invalid stage")
        if existing["stage"] in ("prepared","switched"):
            if not backup.is_file() or sha(backup.read_bytes())!=existing["old_sha"]:raise ValueError("Backup damaged")
            atomic(live,backup.read_bytes());existing["stage"]="rolled_back"
            atomic(state,json.dumps(existing).encode());return "RECOVERED_OLD"
        return existing["stage"].upper()
    old,new=live.read_bytes(),candidate.read_bytes()
    if old==new:raise ValueError("Not an update")
    atomic(backup,old)
    tx={"stage":"prepared","old_sha":sha(old),"new_sha":sha(new)}
    atomic(state,json.dumps(tx).encode())
    if crash=="after_prepared":raise RuntimeError("SIMULATED_CRASH_PREPARED")
    atomic(live,new);tx["stage"]="switched";atomic(state,json.dumps(tx).encode())
    if crash=="after_switched":raise RuntimeError("SIMULATED_CRASH_SWITCHED")
    if not health:
        atomic(live,old);tx["stage"]="rolled_back";atomic(state,json.dumps(tx).encode());return "ROLLED_BACK"
    tx["stage"]="committed";atomic(state,json.dumps(tx).encode());return "COMMITTED"
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--fixture-root",required=True)
    ap.add_argument("--health",choices=["pass","fail"],default="pass")
    ap.add_argument("--simulate-crash",choices=["after_prepared","after_switched"])
    a=ap.parse_args()
    try:print(run(a.fixture_root,a.health=="pass",a.simulate_crash))
    except (ValueError,RuntimeError,OSError,json.JSONDecodeError) as e:ap.exit(1,"REFUSED: "+str(e)+"\n")
