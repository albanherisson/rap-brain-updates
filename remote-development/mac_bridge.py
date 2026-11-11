#!/usr/bin/env python3
"""Run one allowlisted public task; optionally publish a redacted result.

This pilot has no shell execution and cannot modify Rap Brain or its database.
"""

import argparse
import base64
import binascii
import fcntl
import getpass
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from mac_preflight import inspect
from mac_private_source_trial import keychain_token as private_keychain_token, trial as private_trial, trial_commit
from mac_reviewed_test_trial import (run_reviewed_test, COMMIT as REVIEWED_COMMIT,
                                     MANIFEST_SHA256 as REVIEWED_MANIFEST,
                                     SERVER_SHA256 as REVIEWED_SERVER,
                                     TEST_SHA256 as REVIEWED_TEST_SHA)
from mac_manager_lab_trial import run_manager_lab, RUNNER_SHA256 as MANAGER_RUNNER_SHA
from mac_manager_inventory import inspect as inspect_manager, running as manager_running
from pathlib import Path


REPO = "albanherisson/rap-brain-updates"
BRANCH = "p0/remote-development-preflight"
API = "https://api.github.com/repos/" + REPO + "/contents/remote-development/"
TASK_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,49}\Z")
MAX_BYTES = 4096
KEYCHAIN_SERVICE = "com.gns.rapbrain.remote.p0"
KEYCHAIN_ACCOUNT = "albanherisson"
REMOTE_MANAGER_TASK = "pilot-014"
REMOTE_MANAGER_SERVER_SHA = "4cdab9087a33855e79e8fee5d639cae3489fc7a4399cdc6e0099b15ad8a7e16c"
REMOTE_MANAGER_RUNNER_SHA = "495ce0989ed8fd98cb317ef37ac6923ffee5fc1aefad9ff06245c0ac2a5fac9c"
REMOTE_MANAGER_RUNNER = (
    "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
    "964665a91aeaca13719782d6a52b8ac8ba7c937d/remote-development/mac_manager_remote_update_trial.py"
)
REMOTE_MANAGER_PROOF = {
    "status": "pass", "manager_request": "programmatic_verified", "scope": "temporary_copies",
    "external_handoff": "verified", "copy_install": "committed", "copy_rollback": "rolled_back",
    "real_server_health": "verified", "health_refusal": "injected_after_real_probe",
    "macos_codesign": "verified", "synthetic_sqlite_and_config": "preserved",
    "active_sources_unchanged": True, "production_key_used": False,
}


def request(url, method="GET", token=None, payload=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "RapBrainBridgePilot/1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read(16384 + 1)
            if len(body) > 16384:
                raise ValueError("Réponse GitHub trop grande")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == "GET":
            return None
        raise RuntimeError("GitHub HTTP " + str(exc.code)) from None


def contents_url(kind, task_id):
    if kind not in ("tasks", "results") or not TASK_ID.fullmatch(task_id):
        raise ValueError("Identifiant ou type de tâche invalide")
    return API + kind + "/" + task_id + ".json?ref=" + urllib.parse.quote(BRANCH, safe="")


def read_queue(get=request):
    item = get(API + "queue/current.json?ref=" + urllib.parse.quote(BRANCH, safe=""))
    if not isinstance(item, dict) or item.get("type") != "file" or item.get("encoding") != "base64":
        raise ValueError("File d'attente absente ou invalide")
    if not isinstance(item.get("size"), int) or not 0 < item["size"] <= MAX_BYTES:
        raise ValueError("File d'attente trop grande")
    try:
        raw = base64.b64decode(item["content"].replace("\n", ""), validate=True)
        queue = json.loads(raw)
    except (KeyError, AttributeError, binascii.Error, UnicodeError, json.JSONDecodeError):
        raise ValueError("File d'attente illisible") from None
    if len(raw) != item["size"] or not isinstance(queue, dict) or set(queue) != {"schema", "task_id"}:
        raise ValueError("Structure de file d'attente invalide")
    if queue["schema"] != "rapbrain-remote-queue-v1" or not isinstance(queue["task_id"], str) or not TASK_ID.fullmatch(queue["task_id"]):
        raise ValueError("Identifiant de tâche invalide")
    return queue["task_id"]


def read_task(task_id, get=request, now=None):
    item = get(contents_url("tasks", task_id))
    if not isinstance(item, dict) or item.get("type") != "file" or item.get("encoding") != "base64":
        raise ValueError("Tâche GitHub absente ou invalide")
    if not isinstance(item.get("size"), int) or not 0 < item["size"] <= MAX_BYTES:
        raise ValueError("Tâche trop grande")
    encoded = item.get("content", "")
    if not isinstance(encoded, str):
        raise ValueError("Encodage invalide")
    try:
        raw = base64.b64decode(encoded.replace("\n", ""), validate=True)
    except binascii.Error:
        raise ValueError("Base64 invalide") from None
    if len(raw) != item["size"] or len(raw) > MAX_BYTES:
        raise ValueError("Taille de tâche incohérente")
    try:
        task = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("JSON de tâche invalide") from None
    if not isinstance(task, dict) or task.get("id") != task_id:
        raise ValueError("Structure de tâche invalide")
    schema, action = task.get("schema"), task.get("action")
    if schema == "rapbrain-remote-task-v1" and action in ("health_check", "private_source_trial", "manager_inventory", "manager_process"):
        if set(task) != {"schema", "id", "action", "expected_server_sha256"}:
            raise ValueError("Structure de tâche invalide")
    elif schema == "rapbrain-remote-task-v1" and action == "manager_remote_update_trial":
        if (task_id != REMOTE_MANAGER_TASK
                or set(task) != {"schema", "id", "action", "expected_server_sha256", "expires_at"}
                or task["expected_server_sha256"] != REMOTE_MANAGER_SERVER_SHA):
            raise ValueError("Pilote distant du Manager invalide")
        expires = task["expires_at"]
        current = time.time() if now is None else now
        if type(expires) is not int or not current < expires <= current + 7 * 86400:
            raise ValueError("Tâche expirée ou trop éloignée")
    elif schema == "rapbrain-remote-task-v2" and action in ("source_validate", "reviewed_test_trial", "manager_lab_trial"):
        if set(task) != {"schema", "id", "action", "expected_server_sha256", "source_commit",
                         "manifest_sha256", "candidate_server_sha256", "expires_at"}:
            raise ValueError("Structure de tâche invalide")
        for key, length in (("source_commit", 40), ("manifest_sha256", 64), ("candidate_server_sha256", 64)):
            value = task[key]
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value):
                raise ValueError("Identité privée invalide")
        expires = task["expires_at"]
        current = time.time() if now is None else now
        if type(expires) is not int or not current < expires <= current + 7 * 86400:
            raise ValueError("Tâche expirée ou trop éloignée")
        if action in ("reviewed_test_trial", "manager_lab_trial") and (task["source_commit"], task["manifest_sha256"],
                task["candidate_server_sha256"]) != (REVIEWED_COMMIT, REVIEWED_MANIFEST, REVIEWED_SERVER):
            raise ValueError("Version des tests revus inattendue")
    else:
        raise ValueError("Action non autorisée")
    expected = task["expected_server_sha256"]
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Empreinte attendue invalide")
    return task, hashlib.sha256(raw).hexdigest()


def run_manager_remote_update_trial(opener=urllib.request.urlopen, spawn=subprocess.Popen):
    with tempfile.TemporaryDirectory(prefix="rapbrain-remote-manager-runner-") as temporary:
        root = Path(temporary).resolve()
        try:
            with opener(REMOTE_MANAGER_RUNNER, timeout=20) as response:
                raw = response.read(50_001)
                if (response.geturl() != REMOTE_MANAGER_RUNNER or len(raw) > 50_000
                        or hashlib.sha256(raw).hexdigest() != REMOTE_MANAGER_RUNNER_SHA):
                    return {"status": "failed", "reason": "runner_hash_mismatch"}
        except OSError:
            return {"status": "failed", "reason": "runner_download_failed"}
        runner = root / "trial.py"
        runner.write_bytes(raw)
        environment = {"HOME": str(Path.home().resolve()), "TMPDIR": str(root),
                       "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C", "LANG": "C"}
        try:
            with spawn([sys.executable, "-I", "-B", str(runner)], cwd=root, env=environment,
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT) as process:
                try:
                    output, _ = process.communicate(timeout=300)
                except subprocess.TimeoutExpired:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    return {"status": "failed", "reason": "runner_timeout"}
                exit_code = process.returncode
        except OSError:
            return {"status": "failed", "reason": "runner_execution_failed"}
    try:
        proof = json.loads(output.splitlines()[-1]) if len(output) <= 16_384 else None
    except (IndexError, ValueError, UnicodeError):
        proof = None
    if exit_code == 0 and proof == REMOTE_MANAGER_PROOF:
        return REMOTE_MANAGER_PROOF.copy()
    if (exit_code != 0 and isinstance(proof, dict) and proof.keys() == {"status", "reason"}
            and proof["status"] == "failed" and isinstance(proof["reason"], str)
            and re.fullmatch(r"[a-zA-Z0-9_]{1,80}", proof["reason"])):
        return {"status": "failed", "reason": proof["reason"]}
    return {"status": "failed", "reason": "runner_proof_invalid"}


def run(task, task_sha, probe=inspect, private_probe=private_trial, private_token=private_keychain_token,
        source_probe=trial_commit, reviewed_probe=run_reviewed_test, manager_probe=run_manager_lab,
        manager_inventory=inspect_manager, manager_process=manager_running,
        remote_update_trial=run_manager_remote_update_trial):
    info = probe()
    if info["platform"] != "Darwin":
        raise ValueError("Exécution réservée à macOS")
    result = {
        "schema": "rapbrain-remote-result-v1",
        "id": task["id"],
        "task_sha256": task_sha,
        "status": "pass" if info["server_sha256"] == task["expected_server_sha256"] else "version_mismatch",
        "server_sha256": info["server_sha256"],
        "app_present": info["app_present"],
        "manager_present": info["manager_present"],
        "git_available": info["git_available"],
        "ollama_available": info["ollama_available"],
    }
    if task["action"] == "private_source_trial" and result["status"] == "pass":
        private_result = private_probe(private_token())
        if (private_result.get("schema") != "rapbrain-private-source-trial-v1" or
                private_result.get("status") != "pass" or
                private_result.get("temporary_copy_removed") is not True):
            raise RuntimeError("Essai privé incomplet : aucun résultat publié")
        result["private_source"] = {key: private_result[key] for key in
                                    ("source_commit", "files_verified", "python_syntax_verified",
                                     "bytes_verified", "temporary_copy_removed")}
    if task["action"] == "source_validate" and result["status"] == "pass":
        private_result = source_probe(private_token(), task["source_commit"], task["manifest_sha256"],
                                      task["candidate_server_sha256"])
        if (private_result.get("schema") != "rapbrain-private-source-trial-v1" or
                private_result.get("status") != "pass" or
                private_result.get("source_commit") != task["source_commit"] or
                private_result.get("manifest_sha256") != task["manifest_sha256"] or
                private_result.get("temporary_copy_removed") is not True):
            raise RuntimeError("Validation privée incomplète : aucun résultat publié")
        result["private_source"] = {key: private_result[key] for key in
                                    ("source_commit", "manifest_sha256", "files_verified",
                                     "python_syntax_verified", "bytes_verified", "temporary_copy_removed")}
    if task["action"] == "reviewed_test_trial" and result["status"] == "pass":
        private_result = reviewed_probe(private_token())
        check = private_result.get("reviewed_test", {})
        if (private_result.get("schema") != "rapbrain-private-source-trial-v1" or
                private_result.get("status") != "pass" or
                private_result.get("source_commit") != REVIEWED_COMMIT or
                private_result.get("manifest_sha256") != REVIEWED_MANIFEST or
                private_result.get("temporary_copy_removed") is not True or
                check.get("status") != "pass" or check.get("tests_run") != 2 or
                check.get("test_sha256") != REVIEWED_TEST_SHA):
            raise RuntimeError("Tests revus incomplets : aucun résultat publié")
        result["private_source"] = {key: private_result[key] for key in
                                    ("source_commit", "manifest_sha256", "files_verified",
                                     "python_syntax_verified", "bytes_verified", "temporary_copy_removed")}
        result["reviewed_test"] = {key: check[key] for key in
                                   ("status", "tests_run", "test_sha256", "timeout_seconds")}
    if task["action"] == "manager_lab_trial" and result["status"] == "pass":
        private_result = manager_probe(private_token())
        check = private_result.get("manager_lab", {})
        if (private_result.get("schema") != "rapbrain-private-source-trial-v1" or
                private_result.get("status") != "pass" or
                private_result.get("source_commit") != REVIEWED_COMMIT or
                private_result.get("manifest_sha256") != REVIEWED_MANIFEST or
                private_result.get("temporary_copy_removed") is not True or
                check.get("status") != "pass" or check.get("runner_sha256") != MANAGER_RUNNER_SHA or
                check.get("crash_recoveries") != 3 or check.get("successful_activations") != 1 or
                check.get("synthetic_database_preserved") is not True):
            raise RuntimeError("Essai Manager incomplet : aucun résultat publié")
        result["private_source"] = {key: private_result[key] for key in
                                    ("source_commit", "manifest_sha256", "files_verified",
                                     "python_syntax_verified", "bytes_verified", "temporary_copy_removed")}
        result["manager_lab"] = {key: check[key] for key in
                                 ("status", "runner_sha256", "crash_recoveries",
                                  "successful_activations", "synthetic_database_preserved")}
    if task["action"] == "manager_inventory" and result["status"] == "pass":
        inventory = manager_inventory()
        if inventory.get("schema") != "rapbrain-manager-inventory-v1":
            raise RuntimeError("Inventaire Manager invalide")
        result["manager_inventory"] = inventory
    if task["action"] == "manager_process" and result["status"] == "pass":
        process = manager_process()
        fields = ("applications_bundle_running", "beta14_bundle_running",
                  "server_running", "port_8765_listening")
        if (not isinstance(process, dict) or process.get("schema") != "rapbrain-manager-process-v1" or
                any(type(process.get(key)) is not bool for key in fields)):
            raise RuntimeError("Inventaire des processus invalide")
        result["manager_process"] = {key: process[key] for key in fields}
    if task["action"] == "manager_remote_update_trial" and result["status"] == "pass":
        proof = remote_update_trial()
        result["status"] = proof["status"]
        result["manager_remote_update"] = {**proof, "runner_sha256": REMOTE_MANAGER_RUNNER_SHA}
    return result


def publish(task_id, result, token, get=request):
    url = contents_url("results", task_id)
    if get(url, token=token) is not None:
        raise ValueError("Résultat déjà publié : aucune réécriture")
    raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    payload = json.dumps({"message": "P0: pilot result " + task_id,
                          "content": base64.b64encode(raw).decode(), "branch": BRANCH}).encode()
    return get(url.split("?", 1)[0], method="PUT", token=token, payload=payload)


def watch_once(token, get=request, probe=inspect, remote_update_trial=run_manager_remote_update_trial):
    task_id = read_queue(get)
    if get(contents_url("results", task_id), token=token) is not None:
        return task_id, "already_published"
    task, task_sha = read_task(task_id, get=get)
    result = run(task, task_sha, probe=probe, remote_update_trial=remote_update_trial)
    publish(task_id, result, token, get=get)
    return task_id, result["status"]


def watch(token, interval=60):
    previous = None
    while True:
        try:
            task_id, status = watch_once(token)
            current = task_id + ": " + status
            if current != previous:
                print(current, flush=True)
            previous = current
        except (ValueError, RuntimeError, urllib.error.URLError) as exc:
            print("Pont en attente : " + str(exc), file=sys.stderr, flush=True)
            previous = None
        time.sleep(interval)


def keychain_token(run_command=subprocess.run):
    args = ["/usr/bin/security", "find-generic-password", "-a", KEYCHAIN_ACCOUNT,
            "-s", KEYCHAIN_SERVICE, "-w"]
    try:
        result = run_command(args, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Trousseau indisponible") from None
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Jeton absent du trousseau ou accès refusé")
    token = result.stdout.strip()
    if "\n" in token or "\r" in token or not token.startswith("github_pat_"):
        raise RuntimeError("Format du jeton inattendu")
    return token


def agent_lock(home=None):
    home = Path.home() if home is None else Path(home)
    directory = home / "Library" / "Application Support" / "RapBrainRemoteBridge"
    if directory.is_symlink():
        raise RuntimeError("Dossier du pont remplacé par un lien")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "agent.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError("Une veille du pont fonctionne déjà") from None
    return fd


def main():
    parser = argparse.ArgumentParser(description="Tâche distante Rap Brain, pilote limité")
    parser.add_argument("task_id", nargs="?")
    parser.add_argument("--publish", action="store_true", help="Publier uniquement le résultat expurgé")
    parser.add_argument("--watch", action="store_true", help="Surveiller les tâches tant que ce Terminal reste ouvert")
    parser.add_argument("--watch-keychain", action="store_true", help="Veille avec jeton du trousseau macOS")
    parser.add_argument("--check-keychain", action="store_true", help="Vérifier l'accès au jeton sans l'afficher")
    args = parser.parse_args()
    if args.check_keychain:
        if args.task_id or args.publish or args.watch or args.watch_keychain:
            parser.error("--check-keychain s'utilise seul")
        token = keychain_token()
        token = ""
        print("Trousseau Rap Brain : jeton accessible")
        return
    if args.watch_keychain:
        if args.task_id or args.publish or args.watch:
            parser.error("--watch-keychain s'utilise seul")
        lock = agent_lock()
        try:
            token = keychain_token()
            try:
                watch(token)
            finally:
                token = ""
        finally:
            os.close(lock)
        return
    if args.watch:
        if args.task_id or args.publish:
            parser.error("--watch n'accepte ni identifiant ni --publish")
        lock = agent_lock()
        token = getpass.getpass("Jeton GitHub à portée Contents écriture pour ce dépôt : ")
        try:
            watch(token)
        finally:
            token = ""
            os.close(lock)
        return
    if not args.task_id:
        parser.error("identifiant de tâche requis")
    task, task_sha = read_task(args.task_id)
    result = run(task, task_sha)
    print(json.dumps(result, sort_keys=True))
    if args.publish:
        token = getpass.getpass("Jeton GitHub à portée Contents écriture pour ce dépôt : ")
        try:
            publish(args.task_id, result, token)
        finally:
            token = ""
        print("Résultat publié sur la branche P0.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, urllib.error.URLError) as exc:
        print("Pont refusé : " + str(exc), file=sys.stderr)
        raise SystemExit(1)
