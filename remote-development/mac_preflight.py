#!/usr/bin/env python3
"""Read-only, low-disclosure preflight for the Rap Brain Mac bridge."""

import hashlib
import json
import platform
import shutil
from pathlib import Path


def digest(path):
    if not path.is_file() or path.is_symlink():
        return None
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def inspect(home=None, which=shutil.which, system=platform.system):
    home = Path.home() if home is None else Path(home)
    app = home / "Downloads" / "rap-brain"
    manager = home / "Applications" / "Rap Brain Manager.app"
    server = app / "server.py"
    db = app / "data" / "rapbrain.sqlite3"
    app_present = app.is_dir() and not app.is_symlink()
    return {
        "schema": "rapbrain-remote-preflight-v1",
        "platform": system(),
        "python": platform.python_version(),
        "app_present": app_present,
        "server_sha256": digest(server) if app_present else None,
        "database_present": app_present and db.is_file() and not db.is_symlink(),
        "manager_present": manager.is_dir() and not manager.is_symlink(),
        "git_available": which("git") is not None,
        "ollama_available": which("ollama") is not None,
    }


if __name__ == "__main__":
    print(json.dumps(inspect(), sort_keys=True, ensure_ascii=False))
