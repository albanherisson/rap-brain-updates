"""Safe, executable child lifecycle fixture using READY handshake over stdout.

No TCP ports, no PID files, no discovery/signaling of external processes.
Only stops child handles this process directly created.
"""
import os, select, subprocess, sys, tempfile
from pathlib import Path

CHILD = """import sys,time
print('READY:'+sys.argv[1],flush=True)
while True: time.sleep(0.1)
"""
class ChildError(RuntimeError):pass
class OwnedChild:
    def __init__(self):
        self.process=None
    def start(self,script,version):
        if self.process is not None:raise ChildError("Already owns a child")
        if version not in ("old","new"):raise ChildError("Unsafe fixture version")
        if not Path(script).is_file():raise ChildError("Missing fixture")
        process=subprocess.Popen([sys.executable,str(script),version],stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
        self.process=process
        try:
            readable,_,_=select.select([process.stdout],[],[],4)
            if not readable or process.stdout.readline()!=("READY:"+version+"\n").encode() or process.poll() is not None:
                raise ChildError("Owned child health check failed")
        except BaseException:
            self.stop()
            raise
        return process.pid
    def stop(self):
        process=self.process
        if process is None:return
        self.process=None
        try:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        finally:
            if process.stdout is not None:process.stdout.close()

def transaction(fail_health=False):
    """Only an auto-created temp directory containing fake Manager data is changed."""
    with tempfile.TemporaryDirectory(prefix="rapbrain-owned-fixture-") as dirname:
        root=Path(dirname)
        script=root/"owned_child.py"
        script.write_text(CHILD)
        target=root/"manager.fixture"
        target.write_bytes(b"old")
        worker=OwnedChild()
        try:
            worker.start(script,"old")
            worker.stop()
            staged=root/"manager.new"
            staged.write_bytes(b"new")
            os.replace(staged,target)
            worker.start(script,"new")
            if fail_health:
                worker.stop()
                staged=root/"manager.restore"
                staged.write_bytes(b"old")
                os.replace(staged,target)
                worker.start(script,"old")
                if target.read_bytes()!=b"old":raise ChildError("Rollback mismatch")
                return "ROLLED_BACK"
            if target.read_bytes()!=b"new":raise ChildError("Update mismatch")
            return "COMMITTED"
        finally:
            worker.stop()
