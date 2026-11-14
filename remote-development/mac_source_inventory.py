#!/usr/bin/env python3
"""Inventory known Rap Brain roots locally without reading private file contents."""

import json
import os
import stat
from collections import Counter
from pathlib import Path


SOURCE_SUFFIXES = {".py", ".js", ".css", ".html", ".swift", ".sh", ".command"}
PRIVATE_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".pem", ".key", ".p12", ".pfx"}
REVIEW_SUFFIXES = {".json", ".toml", ".yaml", ".yml", ".env", ".plist"}


def classify(relative):
    name = relative.name.lower()
    suffix = relative.suffix.lower()
    if suffix in PRIVATE_SUFFIXES or suffix == ".env" or name.startswith(".env") or any(x in name for x in ("token", "secret", "credential", "private")):
        return "private_data"
    if suffix in (".log", ".bak", ".backup", ".zip") or "backup" in name:
        return "backup_or_log"
    if suffix in REVIEW_SUFFIXES:
        return "review_required"
    if suffix in SOURCE_SUFFIXES:
        return "source_candidate"
    return "other"


def scan_root(root, limit=100000):
    root = Path(root)
    counts, bytes_by_kind, source_paths = Counter(), Counter(), []
    if root.is_symlink() or not root.is_dir():
        return {"present": False, "counts": {}, "bytes": {}, "source_paths": []}
    visited = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(current) / d).is_symlink()]
        for name in files:
            visited += 1
            if visited > limit:
                raise RuntimeError("Inventaire trop grand : arrêt sans rapport partiel")
            path = Path(current) / name
            try:
                info = path.lstat()
            except OSError:
                counts["unreadable"] += 1
                continue
            if not stat.S_ISREG(info.st_mode):
                counts["not_regular"] += 1
                continue
            relative = path.relative_to(root)
            kind = classify(relative)
            counts[kind] += 1
            bytes_by_kind[kind] += info.st_size
            if kind == "source_candidate":
                source_paths.append(relative.as_posix())
    return {"present": True, "counts": dict(counts), "bytes": dict(bytes_by_kind),
            "source_paths": sorted(source_paths)}


def inventory(home=None):
    home = Path.home() if home is None else Path(home)
    roots = {
        "rap_brain": home / "Downloads" / "rap-brain",
        "manager_app": home / "Applications" / "Rap Brain Manager.app",
        "manager_backups": home / "Downloads" / "RapBrainManagerBackups",
    }
    return {"schema": "rapbrain-local-inventory-v1",
            "roots": {key: scan_root(path) for key, path in roots.items()},
            "note": "Local only. Source candidates require secret review before any GitHub upload."}


def main():
    report = inventory()
    home = Path.home()
    directory = home / "Library" / "Application Support" / "RapBrainRemoteBridge"
    if directory.is_symlink():
        raise RuntimeError("Dossier du pont remplacé par un lien")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = directory / "source_inventory.json"
    if target.exists() or target.is_symlink():
        raise RuntimeError("Inventaire existant : aucun écrasement")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    safe = {name: {"present": item["present"], "counts": item["counts"], "bytes": item["bytes"]}
            for name, item in report["roots"].items()}
    print(json.dumps({"schema": report["schema"], "roots": safe}, sort_keys=True))


if __name__ == "__main__":
    main()
