#!/usr/bin/env python3
"""Read-only Manager launch audit: no process start/stop, private files, or HTML output."""
import hashlib,json
from pathlib import Path
import stat, subprocess
from urllib.request import urlopen

APP=Path.home()/"Applications/Rap Brain Manager.app"
STATE=Path.home()/"Library/Application Support/RapBrainManager/launch-state.json"
MAIN=APP/"Contents/Resources/manager.py"
LAUNCHER=APP/"Contents/Resources/launcher.py"
BIN=APP/"Contents/MacOS/RapBrainManager"
EXPECTED_MAIN="bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"

def regular(path,limit=1000000):
    try:
        s=path.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_size>limit:return None
        return path.read_bytes()
    except (OSError,ValueError):return None

def parse_state(raw):
    if raw is None or not 0<len(raw)<=8192:return None
    try:d=json.loads(raw)
    except (UnicodeError,ValueError):return None
    if type(d) is not dict or set(d)!={"pid","port"}:return None
    pid,port=d["pid"],d["port"]
    if type(pid) is not int or not (2<=pid<=4194304):return None
    if type(port) is not int or not (1024<=port<=65535):return None
    return pid,port

def process_matches(pid):
    try:
        r=subprocess.run(["/bin/ps","-p",str(pid),"-o","command="],capture_output=True,text=True,timeout=3)
        return r.returncode==0 and str(MAIN) in r.stdout
    except (OSError,subprocess.TimeoutExpired):return False

def probe(port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/",timeout=2) as r:
            return r.status==200 and "text/html" in r.headers.get("Content-Type","").lower()
    except Exception:return False

def main():
    print("RAP BRAIN MANAGER — AUDIT EN LECTURE SEULE")
    for label,path in [("manager.py",MAIN),("launcher.py",LAUNCHER),("lanceur MacOS",BIN)]:
        data=regular(path)
        if data is None:print(label+": ABSENT / FORMAT NON ADMIS")
        else:
            digest=hashlib.sha256(data).hexdigest()
            marker=" (empreinte du Manager connue)" if label=="manager.py" and digest==EXPECTED_MAIN else ""
            print(f"{label}: présent, {len(data)} octets, sha256={digest}{marker}")
    state=parse_state(regular(STATE,8192))
    if state is None:
        print("État lanceur: absent ou invalide; aucun serveur démarré")
    else:
        pid,port=state
        print(f"État lanceur: PID {pid}, port local {port}")
        match=process_matches(pid)
        print("Processus du Manager reconnu:", "OUI" if match else "NON")
        print("Réponse HTTP locale du Manager:", "OUI" if match and probe(port) else "NON / NON TESTÉE")
    print("Aucune opération de lancement, arrêt, installation ou modification")

if __name__=="__main__":main()
