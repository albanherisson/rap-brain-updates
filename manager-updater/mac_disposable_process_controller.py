"""External process lifecycle controller for disposable subprocesses ONLY.

No PID-based signalling. This does not import or launch the real Rap Brain Manager.
A process is stoppable only through the exact Popen object created by this controller.
"""
import os
from pathlib import Path
import subprocess
import sys
import time
from mac_lifecycle_policy import Refused

class OwnedProcess:
    def __init__(self, *, marker, script, timeout=2.0):
        self.marker=Path(marker)
        self.script=Path(script)
        self.timeout=timeout
        self._proc=None
        self._identity=None

    def _check_fixture(self):
        if self.marker.name!="fixture.marker" or self.marker.is_symlink():
            raise Refused("Only disposable fixture marker accepted")
        if self.marker.read_bytes()!=b"RAPBRAIN_DISPOSABLE_PROCESS_V1\n":
            raise Refused("Fixture marker invalid")
        if self.script.is_symlink() or not self.script.is_file():
            raise Refused("Fixture script invalid")
        if self.script.parent.resolve()!=self.marker.parent.resolve():
            raise Refused("Fixture script outside fixture directory")
        if self.script.name!="worker.py":
            raise Refused("Unexpected fixture script")

    def launch(self, *, healthy):
        self._check_fixture()
        if self._proc is not None:raise Refused("Process handle already exists")
        if not callable(healthy):raise Refused("Health callback required")
        proc=subprocess.Popen([sys.executable,str(self.script)],stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                              cwd=str(self.script.parent),close_fds=True)
        self._proc=proc
        self._identity=(proc.pid,proc)
        deadline=time.monotonic()+self.timeout
        try:
            while time.monotonic()<deadline:
                if proc.poll() is not None:raise Refused("Worker exited early")
                if healthy(proc) is True:return proc
                time.sleep(.02)
            raise Refused("Worker health check timed out")
        except BaseException:
            self.stop()
            raise

    def stop(self):
        proc=self._proc
        if proc is None:return False
        if self._identity!=(proc.pid,proc):
            raise Refused("Process identity mismatch")
        try:
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=self.timeout)
            return True
        finally:
            self._proc=None
            self._identity=None

    def restart(self, *, healthy):
        if self._proc is None:raise Refused("Cannot restart a process not owned")
        self.stop()
        return self.launch(healthy=healthy)
