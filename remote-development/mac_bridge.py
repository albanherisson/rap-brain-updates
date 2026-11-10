#!/usr/bin/env python3
"""Run one allowlisted public task; optionally publish a redacted result.

This pilot has no shell execution and cannot modify Rap Brain or its database.
"""

import argparse
import base64
import binascii
import getpass
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from mac_preflight import inspect


REPO = "albanherisson/rap-brain-updates"
BRANCH = "p0/remote-development-preflight"
API = "https://api.github.com/repos/" + REPO + "/contents/remote-development/"
TASK_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,49}\Z")
MAX_BYTES = 4096


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


def read_task(task_id, get=request):
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
    task = json.loads(raw)
    if not isinstance(task, dict) or set(task) != {"schema", "id", "action", "expected_server_sha256"}:
        raise ValueError("Structure de tâche invalide")
    if task["schema"] != "rapbrain-remote-task-v1" or task["id"] != task_id or task["action"] != "health_check":
        raise ValueError("Action non autorisée")
    expected = task["expected_server_sha256"]
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Empreinte attendue invalide")
    return task, hashlib.sha256(raw).hexdigest()


def run(task, task_sha, probe=inspect):
    info = probe()
    if info["platform"] != "Darwin":
        raise ValueError("Exécution réservée à macOS")
    return {
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


def publish(task_id, result, token, get=request):
    url = contents_url("results", task_id)
    if get(url, token=token) is not None:
        raise ValueError("Résultat déjà publié : aucune réécriture")
    raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    payload = json.dumps({"message": "P0: pilot result " + task_id,
                          "content": base64.b64encode(raw).decode(), "branch": BRANCH}).encode()
    return get(url.split("?", 1)[0], method="PUT", token=token, payload=payload)


def watch_once(token, get=request, probe=inspect):
    task_id = read_queue(get)
    if get(contents_url("results", task_id), token=token) is not None:
        return task_id, "already_published"
    task, task_sha = read_task(task_id, get=get)
    result = run(task, task_sha, probe=probe)
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


def main():
    parser = argparse.ArgumentParser(description="Tâche distante Rap Brain, pilote limité")
    parser.add_argument("task_id", nargs="?")
    parser.add_argument("--publish", action="store_true", help="Publier uniquement le résultat expurgé")
    parser.add_argument("--watch", action="store_true", help="Surveiller les tâches tant que ce Terminal reste ouvert")
    args = parser.parse_args()
    if args.watch:
        if args.task_id or args.publish:
            parser.error("--watch n'accepte ni identifiant ni --publish")
        token = getpass.getpass("Jeton GitHub à portée Contents écriture pour ce dépôt : ")
        try:
            watch(token)
        finally:
            token = ""
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
