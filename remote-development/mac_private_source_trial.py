#!/usr/bin/env python3
"""Read a pinned private source snapshot into a disposable, isolated directory.

The optional reviewed callback runs only after hash verification in the temporary copy.
The installed app is never touched.
"""

import argparse
import ast
import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath


REPO = "albanherisson/rap-brain-source"
COMMIT = "629b95df0cf28e21db941b82a823561d388eac67"
MANIFEST = "remote-development/source_manifest.json"
MANIFEST_SHA256 = "31236459f934145cc20b7274beeaf910c318cee0639325e7496021b0fa3233c7"
EXPECTED_SERVER = "4cdab9087a33855e79e8fee5d639cae3489fc7a4399cdc6e0099b15ad8a7e16c"
KEYCHAIN_SERVICE = "com.gns.rapbrain.source.readonly.p0"
ACCOUNT = "albanherisson"
API = "https://api.github.com/repos/" + REPO + "/contents/"
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
MAX_FILES = 100
SUFFIXES = {".py", ".js", ".css", ".html", ".swift", ".sh", ".command"}
EXCLUDED = {".git", "data", "backup", "backups", "sauvegardes", "logs", "log", ".venv", "venv"}


def keychain_token(run=subprocess.run):
    try:
        result = run(["/usr/bin/security", "find-generic-password", "-a", ACCOUNT,
                      "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True,
                     text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Trousseau indisponible") from None
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("Jeton privé en lecture seule absent du trousseau")
    token = result.stdout.strip()
    if not token.startswith("github_pat_") or "\n" in token or "\r" in token:
        raise RuntimeError("Format du jeton inattendu")
    return token


def github_file(path, token, commit=COMMIT, opener=urllib.request.urlopen):
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Commit privé invalide")
    url = API + urllib.parse.quote(path, safe="/") + "?ref=" + commit
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "RapBrainPrivateSourceTrial/1",
        "Authorization": "Bearer " + token})
    try:
        with opener(request, timeout=20) as response:
            raw = response.read(3 * MAX_FILE + 4096)
            if len(raw) >= 3 * MAX_FILE + 4096:
                raise RuntimeError("Réponse GitHub trop grande")
    except urllib.error.HTTPError as exc:
        raise RuntimeError("GitHub HTTP " + str(exc.code)) from None
    try:
        item = json.loads(raw)
        if item["type"] != "file" or item["encoding"] != "base64" or item["path"] != path:
            raise ValueError("Fichier GitHub inattendu")
        content = base64.b64decode(item["content"].replace("\n", ""), validate=True)
        if len(content) != item["size"] or len(content) > MAX_FILE:
            raise ValueError("Taille GitHub incohérente")
        return content
    except (KeyError, TypeError, ValueError, binascii.Error, UnicodeError, json.JSONDecodeError):
        raise RuntimeError("Réponse GitHub invalide") from None


def validated_manifest(raw, manifest_sha=MANIFEST_SHA256, expected_server=EXPECTED_SERVER):
    if hashlib.sha256(raw).hexdigest() != manifest_sha:
        raise RuntimeError("Manifeste privé différent de la version revue")
    try:
        manifest = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise RuntimeError("Manifeste privé invalide") from None
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "server_sha256", "files"} or
            manifest["schema"] != "rapbrain-private-source-v1" or
            manifest["server_sha256"] != expected_server or
            not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES):
        raise RuntimeError("Structure de manifeste inattendue")
    seen, total = set(), 0
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise RuntimeError("Entrée de manifeste invalide")
        name, size, digest = entry["path"], entry["bytes"], entry["sha256"]
        if not isinstance(name, str) or not name.isascii() or "\\" in name:
            raise RuntimeError("Chemin de source invalide")
        path = PurePosixPath(name)
        if (name != str(path) or path.is_absolute() or len(path.parts) < 2 or path.parts[0] not in ("rap_brain", "manager_app") or
                any(part in ("", ".", "..") or part.lower() in EXCLUDED for part in path.parts) or
                path.suffix.lower() not in SUFFIXES or name in seen):
            raise RuntimeError("Chemin de source non autorisé")
        if type(size) is not int or size < 0 or size > MAX_FILE or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError("Empreinte ou taille invalide")
        seen.add(name)
        total += size
        if total > MAX_TOTAL:
            raise RuntimeError("Sources trop volumineuses")
    if "rap_brain/server.py" not in seen:
        raise RuntimeError("Serveur absent du manifeste")
    return files


def _trial(fetch_file, commit, manifest_sha, expected_server, home=None, check=None):
    home = Path.home() if home is None else Path(home)
    parent = home / "Library" / "Application Support" / "RapBrainRemoteBridge"
    if parent.is_symlink() or not parent.is_dir():
        raise RuntimeError("Dossier du pont absent ou remplacé")
    manifest = validated_manifest(fetch_file(MANIFEST), manifest_sha, expected_server)
    python_files, total, checked = 0, 0, None
    with tempfile.TemporaryDirectory(prefix="private-source-trial-", dir=parent) as directory:
        workspace = Path(directory)
        os.chmod(workspace, 0o700)
        for item in manifest:
            name = item["path"]
            content = fetch_file(name)
            if len(content) != item["bytes"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise RuntimeError("Source différente du manifeste : " + name)
            if name.endswith(".py"):
                try:
                    ast.parse(content.decode("utf-8"), filename=name)
                except (UnicodeError, SyntaxError):
                    raise RuntimeError("Syntaxe Python invalide : " + name) from None
                python_files += 1
            destination = workspace.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(content)
            destination.chmod(0o600)
            total += len(content)
        if hashlib.sha256((workspace / "rap_brain" / "server.py").read_bytes()).hexdigest() != expected_server:
            raise RuntimeError("Serveur inattendu")
        if check is not None:
            checked = check(workspace, manifest)
    if workspace.exists():
        raise RuntimeError("Copie temporaire non supprimée")
    result = {"schema": "rapbrain-private-source-trial-v1", "status": "pass", "source_commit": commit,
            "manifest_sha256": manifest_sha,
            "files_verified": len(manifest), "python_syntax_verified": python_files,
            "bytes_verified": total, "temporary_copy_removed": True, "installed_app_untouched": True}
    if checked is not None:
        result["reviewed_test"] = checked
    return result


def trial(token, fetch=github_file, home=None):
    return _trial(lambda path: fetch(path, token), COMMIT, MANIFEST_SHA256, EXPECTED_SERVER, home)


def trial_commit(token, commit, manifest_sha, expected_server, fetch=github_file, home=None, check=None):
    for value, length in ((commit, 40), (manifest_sha, 64), (expected_server, 64)):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value):
            raise RuntimeError("Identité du candidat invalide")
    return _trial(lambda path: fetch(path, token, commit), commit, manifest_sha, expected_server, home, check)


def main():
    parser = argparse.ArgumentParser(description="Essai du code privé en copie temporaire")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-keychain", action="store_true")
    action.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise RuntimeError("Essai réservé au Mac")
    token = keychain_token()
    if args.check_keychain:
        print("Trousseau privé : jeton accessible")
    else:
        print(json.dumps(trial(token), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, urllib.error.URLError) as exc:
        print("Essai privé refusé : " + str(exc), file=sys.stderr)
        raise SystemExit(1)
