#!/usr/bin/env python3
"""Exercise the reviewed Manager's two-file journal on disposable source copies."""

import hashlib
import resource
import shutil
import sqlite3
import subprocess
import sys

from mac_private_source_trial import github_file, trial_commit
from mac_reviewed_test_trial import COMMIT, MANIFEST_SHA256, SERVER_SHA256


RUNNER = "manager_app/Contents/Resources/engine/multi_file_trial.py"
RUNNER_SHA256 = "23ab7979dc85e3c6efa5f1256d58fbc5304cad9b47ca532ebb65ff74f6be43e7"
FILES = {"server.py": SERVER_SHA256,
         "creative_engine.py": "b770bdf034caa600f75497325f80759d4f372258fa0e911e28f29d214abe85f3"}
PHASES = ("before_first", "after_first", "after_second", "success")


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_manager_lab(token, home=None, fetch=github_file, call=subprocess.run):
    def check(workspace, manifest):
        indexed = {item["path"]: item["sha256"] for item in manifest}
        expected = {RUNNER: RUNNER_SHA256,
                    **{"rap_brain/" + name: sha for name, sha in FILES.items()}}
        if any(indexed.get(path) != sha or digest(workspace / path) != sha
               for path, sha in expected.items()):
            raise RuntimeError("Laboratoire Manager différent du code revu")
        lab = workspace / "manager-journal-lab"
        lab.mkdir(mode=0o700)
        clone, backup = lab / "clone", lab / "backup"
        clone.mkdir(mode=0o700)
        backup.mkdir(mode=0o700)
        (clone / "data").mkdir(mode=0o700)
        for name in FILES:
            payload = (workspace / "rap_brain" / name).read_bytes()
            (clone / name).write_bytes(payload)
            (backup / name).write_bytes(payload)
        database = clone / "data" / "rapbrain.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE lab_marker (phase TEXT)")
            db.execute("INSERT INTO lab_marker VALUES ('baseline')")
        environment = {"HOME": str(workspace), "TMPDIR": str(workspace),
                       "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
        for phase in PHASES:
            for name, sha in FILES.items():
                shutil.copy2(backup / name, clone / name)
                if digest(clone / name) != sha:
                    raise RuntimeError("Copie du code Manager invalide")
            journal = lab / ("journal-" + phase)
            journal.mkdir(mode=0o700)
            args = [sys.executable, "-I", "-B", str(workspace / RUNNER),
                    "--clone", str(clone), "--backup", str(backup),
                    "--journal-dir", str(journal), "--phase", phase]
            try:
                outcome = call(args, cwd=lab, env=environment, stdin=subprocess.DEVNULL,
                               capture_output=True, timeout=20, check=False, close_fds=True,
                               start_new_session=True, preexec_fn=limits)
            except subprocess.TimeoutExpired:
                raise RuntimeError("Essai Manager trop long ; copie supprimée") from None
            if outcome.returncode != (0 if phase == "success" else 73):
                raise RuntimeError("Activation fictive Manager inattendue")
            if phase != "success":
                if not (journal / "transaction.json").is_file():
                    raise RuntimeError("Journal de reprise Manager absent")
                with sqlite3.connect(database) as db:
                    db.execute("INSERT INTO lab_marker VALUES (?)", (phase,))
                args = [sys.executable, "-I", "-B", str(workspace / RUNNER),
                        "--clone", str(clone), "--backup", str(backup),
                        "--journal-dir", str(journal), "--recover"]
                try:
                    recovered = call(args, cwd=lab, env=environment, stdin=subprocess.DEVNULL,
                                     capture_output=True, timeout=20, check=False, close_fds=True,
                                     start_new_session=True, preexec_fn=limits)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("Reprise Manager trop longue ; copie supprimée") from None
                if recovered.returncode != 0:
                    raise RuntimeError("Retour arrière Manager échoué")
            if phase == "success":
                if any(digest(clone / name) == sha for name, sha in FILES.items()):
                    raise RuntimeError("Activation fictive Manager absente")
                for name in FILES:
                    shutil.copy2(backup / name, clone / name)
            if (journal / "transaction.json").exists() or any(
                    digest(clone / name) != sha for name, sha in FILES.items()):
                raise RuntimeError("Code Manager non restauré sur la copie")
            with sqlite3.connect(database) as db:
                count = db.execute("SELECT COUNT(*) FROM lab_marker").fetchone()[0]
                if count != 1 + min(PHASES.index(phase) + 1, 3):
                    raise RuntimeError("Donnée fictive perdue pendant la reprise")
        return {"status": "pass", "runner_sha256": RUNNER_SHA256,
                "crash_recoveries": 3, "successful_activations": 1,
                "synthetic_database_preserved": True}

    result = trial_commit(token, COMMIT, MANIFEST_SHA256, SERVER_SHA256,
                          fetch=fetch, home=home, check=check)
    # trial_commit stores callbacks under reviewed_test; present the lab's own name.
    checked = result.pop("reviewed_test", None)
    if checked is None or checked.get("status") != "pass":
        raise RuntimeError("Essai Manager incomplet")
    result["manager_lab"] = checked
    return result
