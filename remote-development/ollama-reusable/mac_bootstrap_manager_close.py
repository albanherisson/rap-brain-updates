#!/usr/bin/env python3
"""Fetch pinned public bridge files and activate Manager-only close."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request


COMMIT = "2d0a221a79f63dc20e2b107ad1e517aa7167ffe0"
BASE = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/" + COMMIT + "/"
FILES = {
    "mac_manager_lifecycle_request.py": (
        "remote-development/ollama-reusable/mac_manager_lifecycle_request.py",
        "ae9c4a6a72ad5af53a46fb49229fa7cbf79c7a0be3ab956d22ac367c87203d66"),
    "mac_activate_manager_close.py": (
        "remote-development/ollama-reusable/mac_activate_manager_close.py",
        "44cedcef56415a53ae4aab1d6c0a77d95b35d8ea66836713971a18d7d29c022e"),
    "mac_install_agent.py": (
        "remote-development/mac_install_agent.py",
        "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"),
}


def main():
    if sys.platform != "darwin" or len(sys.argv) != 1:
        raise ValueError("Cette activation est réservée au Mac Rap Brain.")
    with tempfile.TemporaryDirectory(prefix="rapbrain-close-manager-") as directory:
        root = Path(directory)
        for filename, (path, digest) in FILES.items():
            url = BASE + path
            with urllib.request.urlopen(url, timeout=20) as response:
                raw = response.read(100_001)
                if response.geturl() != url:
                    raise ValueError("Source inattendue.")
            if len(raw) > 100_000 or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("Empreinte inattendue.")
            (root / filename).write_bytes(raw)
        result = subprocess.run([sys.executable, str(root / "mac_activate_manager_close.py")],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ValueError(result.stderr.strip() or "Activation refusée.")
        print(result.stdout.strip())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
