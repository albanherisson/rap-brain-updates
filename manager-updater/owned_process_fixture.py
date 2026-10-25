"""Owned-process lifecycle adapter, disposable subprocesses ONLY.

The controller accepts only Popen handles it created. It cannot take a PID,
cannot attach to already-running processes, and cannot operate on installed apps.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import os
import stat
import subprocess
import sys
import tempfile

MARKER=b"RAPBRAIN_DISPOSABLE_PROCESS_V1\n"
class Refuse(RuntimeError): pass

@dataclass
class OwnedProcess:
    process: subprocess.Popen
    script: Path
    expected_sha256: str
    root: Path

def _regular_bytes(path):
    st=path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size>8192:raise Refuse("Unsafe fixture script")
    return path.read_bytes()

def prepare_fixture(root):
    root=Path(root).absolute()
    if root.name!="DisposableProcessFixture" or not root.is_dir() or root.is_symlink():
        raise Refuse("Not a disposable fixture")
    if (root/"fixture.marker").is_symlink() or (root/"fixture.marker").read_bytes()!=MARKER:
        raise Refuse("Fixture marker missing")
    script=root/"fixture_child.py"
    data=_regular_bytes(script)
    return root,script,hashlib.sha256(data).hexdigest()

def start_owned(root):
    root,script,digest=prepare_fixture(root)
    process=subprocess.Popen(
        [sys.executable,"-u",str(script)],
        cwd=str(root),stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,start_new_session=True
    )
    return OwnedProcess(process,script,digest,root)

def owned_is_running(handle):
    if type(handle) is not OwnedProcess:raise Refuse("Not an owned handle")
    root,script,digest=prepare_fixture(handle.root)
    if script!=handle.script or digest!=handle.expected_sha256:
        raise Refuse("Fixture script identity changed")
    if handle.process.args!=[sys.executable,"-u",str(script)]:
        raise Refuse("Unexpected command")
    return handle.process.poll() is None

def stop_owned(handle,timeout=3):
    if not 0<timeout<=10:raise Refuse("Unsafe timeout")
    if not owned_is_running(handle):return "ALREADY_EXITED"
    # Recheck identity immediately before signalling our retained child handle.
    if not owned_is_running(handle):return "ALREADY_EXITED"
    handle.process.terminate()
    try:handle.process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if owned_is_running(handle):
            handle.process.kill()
            handle.process.wait(timeout=timeout)
    if handle.process.poll() is None:raise Refuse("Child failed to exit")
    return "STOPPED_OWN_CHILD"

def read_ready(handle):
    if not owned_is_running(handle):raise Refuse("Owned child not running")
    output=handle.process.stdout.readline()
    if output.strip()!="DISPOSABLE_READY":raise Refuse("Child not healthy")
    return True
