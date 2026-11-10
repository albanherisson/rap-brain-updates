#!/usr/bin/env python3
"""Prepare a bounded, local code-only archive for human review, never upload."""

import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path

from mac_source_inventory import classify


EXPECTED_SERVER = "4cdab9087a33855e79e8fee5d639cae3489fc7a4399cdc6e0099b15ad8a7e16c"
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
MAX_FILES = 500
EXCLUDED_DIRS = {".git", "__pycache__", "data", "backup", "backups", "logs", "log", "venv", ".venv"}
SECRET_PATTERNS = (
    re.compile(rb"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"(?i)\b[A-Za-z_]*(?:token|secret|password|api[_-]?key)[A-Za-z_]*\s*[:=]\s*['\"][A-Za-z0-9_./+=-]{12,}['\"]"),
    re.compile(rb"(?i)Bearer\s+[A-Za-z0-9_.-]{20,}"),
)


def candidates(root, label):
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(label + " absent ou remplacé par un lien")
    found = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIRS
                   and not (Path(current) / d).is_symlink()]
        for name in files:
            path = Path(current) / name
            if not stat.S_ISREG(path.lstat().st_mode):
                continue
            relative = path.relative_to(root)
            if classify(relative) == "source_candidate":
                found.append((label + "/" + relative.as_posix(), path))
                if len(found) > MAX_FILES:
                    raise RuntimeError("Trop de sources candidates")
    return sorted(found)


def prepare(home=None, target=None, expected_server=EXPECTED_SERVER):
    home = Path.home() if home is None else Path(home)
    roots = ((home / "Downloads" / "rap-brain", "rap_brain"),
             (home / "Applications" / "Rap Brain Manager.app", "manager_app"))
    files = []
    for root, label in roots:
        files.extend(candidates(root, label))
    if not files:
        raise RuntimeError("Aucune source candidate")
    total, entries = 0, []
    for archive_name, path in sorted(files):
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
            raise RuntimeError("Source trop grande ou changée : " + archive_name)
        content = path.read_bytes()
        after = path.lstat()
        if before.st_ino != after.st_ino or before.st_mtime_ns != after.st_mtime_ns or len(content) != after.st_size:
            raise RuntimeError("Source modifiée pendant l'inventaire : " + archive_name)
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            raise RuntimeError("Secret potentiel détecté : " + archive_name)
        total += len(content)
        if total > MAX_TOTAL:
            raise RuntimeError("Paquet source trop grand")
        entries.append((archive_name, content))
    server = next((body for name, body in entries if name == "rap_brain/server.py"), None)
    if server is None or hashlib.sha256(server).hexdigest() != expected_server:
        raise RuntimeError("Version du serveur inattendue : aucun paquet créé")
    target = home / "Desktop" / "RapBrain_Source_Review_P0.zip" if target is None else Path(target)
    if target.parent.is_symlink() or not target.parent.is_dir() or target.exists() or target.is_symlink():
        raise RuntimeError("Destination absente ou déjà occupée")
    manifest = {"schema": "rapbrain-source-review-v1", "server_sha256": expected_server,
                "files": [{"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
                          for name, body in entries],
                "note": "Code candidat uniquement. Revue humaine requise avant GitHub."}
    fd, temp = tempfile.mkstemp(prefix=".rapbrain-review-", suffix=".zip", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in entries:
                archive.writestr(name, body)
            archive.writestr("_manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
        os.chmod(temp, 0o600)
        with zipfile.ZipFile(temp) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Paquet ZIP invalide")
        os.link(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return {"status": "prepared_local_only", "files": len(entries), "bytes": total,
            "archive_sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "path": str(target)}


if __name__ == "__main__":
    try:
        print(json.dumps(prepare(), sort_keys=True))
    except RuntimeError as exc:
        print("Préparation refusée : " + str(exc))
        raise SystemExit(1)
