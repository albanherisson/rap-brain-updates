#!/usr/bin/env python3
"""Start, stop and restart an OWNED dummy localhost HTTP process. Never contacts Manager."""
from pathlib import Path
import socket, subprocess, sys, tempfile, time, urllib.request

SERVER='''import http.server,sys
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.send_header("Content-Type","text/plain")
  self.end_headers();self.wfile.write(b"FIXTURE_ONLY\\n")
 def log_message(self,*args):pass
http.server.ThreadingHTTPServer(("127.0.0.1",int(sys.argv[1])),Handler).serve_forever()
'''

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]

def healthy(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/",timeout=.2) as r:
            return r.status==200 and r.read(64)==b"FIXTURE_ONLY\n"
    except Exception:return False

def launch(script,port):
    p=subprocess.Popen([sys.executable,str(script),str(port)],start_new_session=True,
                       stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    end=time.monotonic()+3
    while time.monotonic()<end:
        if p.poll() is not None:break
        if healthy(port):return p
        time.sleep(.04)
    stop(p)
    details=(p.stderr.read() if p.stderr is not None else "")[:1200]
    raise RuntimeError("Fixture launch failed; child stderr: "+details)

def stop(p):
    # Only a Popen handle created by this test is accepted. No arbitrary PID.
    if p.poll() is None:
        p.terminate()
        try:p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill();p.wait(timeout=3)

def main():
    with tempfile.TemporaryDirectory(prefix="rapbrain-fixture-only-") as tmp:
        script=Path(tmp)/"fixture_http.py"
        script.write_text(SERVER)
        port=free_port()
        first=launch(script,port)
        try:
            assert healthy(port)
            pid=first.pid
            stop(first)
            assert not healthy(port)
            second=launch(script,port)
            try:
                assert second.pid != pid and healthy(port)
                print("OK: faux serveur démarré")
                print("OK: arrêt limité au processus créé par le test")
                print("OK: faux serveur redémarré, contrôle de santé réussi")
                print("OK: aucun processus Rap Brain Manager touché")
            finally:stop(second)
        finally:stop(first)

if __name__=="__main__":main()
