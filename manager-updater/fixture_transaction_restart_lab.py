#!/usr/bin/env python3
"""Disposable fixture ONLY: never touches or imports the installed Rap Brain Manager."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

SERVER = '''import http.server,sys
VALUE=sys.argv[2]
class H(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.send_header("Content-Type","text/plain");self.end_headers();self.wfile.write((VALUE+"\\n").encode())
 def log_message(self,*a):pass
http.server.ThreadingHTTPServer(("127.0.0.1",int(sys.argv[1])),H).serve_forever()
'''

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def probe(p, expected):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{p}/', timeout=.25) as r:
            return r.status == 200 and r.read(100) == (expected+'\n').encode()
    except Exception:
        return False

def stop(proc):
    if proc is None: return
    if proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=3)

def launch(script, p, expected):
    proc = subprocess.Popen([sys.executable,str(script),str(p),expected],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL)
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        if proc.poll() is not None: break
        if probe(p,expected): return proc
        time.sleep(.03)
    stop(proc)
    raise RuntimeError('dummy server failed health probe')

def transaction(fail_health=False):
    with tempfile.TemporaryDirectory(prefix='rapbrain-disposable-lifecycle-') as tmp:
        root=Path(tmp)
        script=root/'fixture_http.py';script.write_text(SERVER)
        source=root/'test_manager.py';source.write_bytes(b'original-fixture-v1\n')
        original=source.read_bytes()
        p=port()
        proc=launch(script,p,'old-server')
        try:
            stop(proc);proc=None
            staged=root/'test_manager.py.stage'
            staged.write_bytes(b'updated-fixture-v2\n')
            os.replace(staged,source)
            try:
                proc=launch(script,p,'new-server')
                if fail_health:
                    raise RuntimeError('simulated health failure')
                assert source.read_bytes()==b'updated-fixture-v2\n'
                print('OK: dummy update committed after healthy restart')
            except Exception:
                stop(proc);proc=None
                restored=root/'test_manager.py.restore'
                restored.write_bytes(original)
                os.replace(restored,source)
                proc=launch(script,p,'old-server')
                assert source.read_bytes()==original
                print('OK: dummy update rolled back; old server healthy')
            assert probe(p,'old-server' if fail_health else 'new-server')
        finally:
            stop(proc)

if __name__=='__main__':
    transaction(False)
    transaction(True)
    print('OK: no installed Manager files, keys, or Rap Brain data accessed')
