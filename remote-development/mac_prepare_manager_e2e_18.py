#!/usr/bin/env python3
"""Sign Manager update 18 and prove verified reopening on disposable copies."""

import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request
from unittest.mock import patch

PREVIOUS = ("https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
            "9f016488aea8679054836930607de4c29265524f/remote-development/mac_prepare_manager_e2e_17.py")
PREVIOUS_SHA = "1178b2f9aafd6dd04f77c8c8add9201750b7b0f46a3d31097efa06bc43295183"
STABLE_SHA = "816b131c5f78b2b71d76c0b1da46ac555026b69fd714fbef643a43d99825f370"
DASHBOARD_SHA = "b5c10d480cac089e71b05e4d7040c11b986c6b606706b8383c470361e55a09bc"
BRIDGE_SHA = "9a3414c93c6961c3091fb3cf8ffd66eec736fd04de41e9d0af57848b7129c87e"
OUTPUT = "RapBrain_Manager_Update_18_Candidate.zip"
OLD = "La version précédente a été restaurée. Le serveur a redémarré."
NEW = "La version précédente a été restaurée. Son serveur a passé le contrôle de santé."

COPY_MANAGER = '''
from pathlib import Path
import sys
path, port = Path(sys.argv[1]), sys.argv[2]
scope = {"__file__": str(path), "__name__": "e2e18_copy"}
exec(compile(path.read_bytes(), str(path), "exec"), scope)
scope["CHILD"] = scope["CHILD"].replace("8765", port)
scope["REMOTE_MANAGER_PORT"] = int(port)
sys.argv = [str(path), "--no-browser"]
raise SystemExit(scope["main"]())
'''


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def replace_once(source, old, new):
    require(source.count(old) == 1, "e2e18_trial_anchor_changed")
    return source.replace(old, new, 1)


def dashboard_candidate(raw):
    require(sha(raw) == DASHBOARD_SHA, "e2e18_dashboard_baseline_changed")
    return replace_once(raw.decode("utf-8"), OLD, NEW).encode("utf-8")


def download_previous():
    with urllib.request.urlopen(PREVIOUS, timeout=25) as response:
        raw = response.read(50_001)
        require(response.geturl() == PREVIOUS and len(raw) <= 50_000 and sha(raw) == PREVIOUS_SHA,
                "e2e18_previous_preparer_changed")
    return raw


def previous_preparer(root):
    source = download_previous().decode("utf-8")
    for old, new in (
        ('Séquence 17. Demande distante', 'Séquence 18. Demande distante'),
        ('== {"sequence": 14}', '== {"sequence": 17}'),
        ('receipt.write_text(\'{"sequence":14}\')', 'receipt.write_text(\'{"sequence":17}\')'),
        ('minimum_sequence=16', 'minimum_sequence=17'),
        ('\'"sequence": 17,\\n\')', '\'"sequence": 18,\\n\')'),
    ):
        source = replace_once(source, old, new)
    path = root / "sequence17_preparer.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("sequence17_preparer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SEQUENCE = 18
    module.CHANNEL_SHA = STABLE_SHA
    module.DASHBOARD_SHA = DASHBOARD_SHA
    module.BRIDGE_PINS["mac_manager_install_request.py"] = BRIDGE_SHA
    module.ARCHIVE = "manager-stable/update-18.zip"
    module.OUTPUT = OUTPUT
    module.dashboard_candidate = dashboard_candidate
    return module


def verify_reopening_on_copy(root, runner, home, attempt, state):
    from mac_manager_install_request import APP, LAUNCHER, reopen_manager
    import mac_manager_install_request as adapter

    require(home.parent.parent == root / "remote" and home.name == "home"
            and home.parent.name in ("committed", "rolled_back"), "e2e18_reopen_scope_invalid")
    branch = home.parent
    port = json.loads((branch / "control.json").read_bytes())["port"]
    require(type(port) is int and 1024 <= port <= 65535 and port not in (8765, 11434),
            "e2e18_reopen_port_invalid")
    runtime = branch / "tmp"
    launcher = home / APP / LAUNCHER
    env = {"HOME": str(home), "TMPDIR": str(runtime), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}
    child = None
    starts = 0

    def launch(app):
        nonlocal child, starts
        require(app == home / APP, "e2e18_reopen_target_invalid")
        starts += 1
        if state == "committed" and starts == 1:
            return True  # Accepted by the opener, but no dashboard appears.
        require(child is None, "e2e18_duplicate_copy_dashboard")
        with (branch / "reopened-manager.log").open("xb") as log:
            child = subprocess.Popen([sys.executable, "-I", "-B", "-c", COPY_MANAGER,
                                      str(launcher), str(port)], cwd=branch, env=env,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        return True

    def directories(_call):
        return [path.resolve() for path in runtime.glob("rapbrain-manager-beta-*")
                if path.is_dir() and not path.is_symlink() and path.stat().st_uid == os.getuid()
                and not path.stat().st_mode & 0o077]

    try:
        with patch.object(adapter, "runtime_directories", directories):
            ready = reopen_manager(home, attempt, state, opener=launch)
        require(ready and child is not None and child.poll() is None,
                "e2e18_live_copy_dashboard_unverified")
        require(starts == (2 if state == "committed" else 1), "e2e18_copy_reopen_retry_unproven")
        return True
    finally:
        runner.stop_retained(child)


def prepare(home, root):
    previous = previous_preparer(root)
    configure = previous.configure_harness
    results = []

    def configure_with_reopen_proof(root, helper):
        base, runner, support = configure(root, helper)
        source = inspect.getsource(base.exercise_remote_handoff)
        source = replace_once(source,
            'authorize=authorize, opener=open_copy)\n        expected = ',
            'authorize=authorize, opener=open_copy, reopener=reopen_copy)\n        expected = ')

        def reopen_copy(home, attempt, state, *, opener):
            proof = verify_reopening_on_copy(root, runner, home, attempt, state)
            results.append(state)
            return proof

        base.reopen_copy = reopen_copy
        exec(compile(source, str(base.__file__), "exec"), base.__dict__)
        exercise = base.exercise_remote_handoff

        def exercise_and_verify(*args):
            exercise(*args)
            require(results == ["committed", "rolled_back"], "e2e18_copy_reopen_cases_missing")

        base.exercise_remote_handoff = exercise_and_verify
        return base, runner, support

    previous.configure_harness = configure_with_reopen_proof
    report = previous.prepare(home, root)
    return report | {"bridge_reopen_proof_on_copies": "verified",
                     "accepted_open_without_dashboard": "retried_on_copy"}


def main():
    require(sys.platform == "darwin" and len(sys.argv) == 1, "e2e18_macos_required")
    with tempfile.TemporaryDirectory(prefix="rapbrain-e2e18-") as name:
        report = prepare(Path.home().resolve(), Path(name).resolve())
    print(json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        reason = str(error)
        print(json.dumps({"status": "failed", "reason": reason if re.fullmatch(
            r"[a-zA-Z0-9_]+", reason) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
