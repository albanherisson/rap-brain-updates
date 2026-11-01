"""Authenticated loopback *fixture* server with cooperative shutdown.

Tests run on an ephemeral loopback port; no installed Rap Brain files, PID,
port or credentials are read. The secret is supplied only to the test fixture.
"""
import hashlib
import hmac
import http.server
import secrets
import threading
import urllib.request

class FixtureServer:
    def __init__(self,secret):
        if type(secret) is not bytes or len(secret)<32:raise ValueError("test secret required")
        self.secret=secret
        self.nonce=secrets.token_hex(24)
        self.used=False
        self.http=None
        self.thread=None

    def start(self):
        parent=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path!="/health":
                    self.send_error(404);return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"FIXTURE_HEALTH_OK")
            def do_POST(self):
                if self.path!="/stop":
                    self.send_error(404);return
                length=self.headers.get("Content-Length","")
                if length!="64" or parent.used:
                    self.send_error(403);return
                proof=self.rfile.read(64)
                expected=hmac.new(parent.secret,("fixture-stop-v1:"+parent.nonce).encode(),hashlib.sha256).hexdigest().encode()
                if not hmac.compare_digest(proof,expected):
                    self.send_error(403);return
                parent.used=True
                self.send_response(204)
                self.end_headers()
                threading.Thread(target=parent.http.shutdown,daemon=True).start()
        self.http=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.http.timeout=.2
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        return self.http.server_address[1]

    def stop_as_owner(self):
        # For test teardown only; never a PID signal.
        if self.http:
            self.http.shutdown()
            self.thread.join(timeout=3)
            self.http.server_close()

def authenticated_stop(server,secret,port):
    if not isinstance(server,FixtureServer):raise TypeError("fixture instance required")
    proof=hmac.new(secret,("fixture-stop-v1:"+server.nonce).encode(),hashlib.sha256).hexdigest().encode()
    request=urllib.request.Request("http://127.0.0.1:%d/stop"%port,data=proof,method="POST")
    with urllib.request.urlopen(request,timeout=3) as response:
        if response.status!=204:raise RuntimeError("cooperative stop failed")
    server.thread.join(timeout=3)
    if server.thread.is_alive():raise RuntimeError("server did not exit")
    return True
