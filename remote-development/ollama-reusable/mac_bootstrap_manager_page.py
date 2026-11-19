#!/usr/bin/env python3
"""Fetch pinned public bridge files and activate the fixed Rap Brain page action."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request


COMMIT = "a891530b56bd9b08b711e5c29d4bea22b424cd10"
BASE = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/" + COMMIT + "/"
FILES = {
    "mac_bridge.py": ("remote-development/ollama-reusable/mac_bridge.py",
                      "c1d827115951d700ef99766f3ade0a90dbd0d493162170e26bc352f49b73acfa"),
    "mac_manager_page_request.py": ("remote-development/ollama-reusable/mac_manager_page_request.py",
                                    "785e20b950b172f324f3dd44a910c70ba1375923cf4dd3e5edcc6a5957a0accc"),
    "mac_activate_manager_page.py": ("remote-development/ollama-reusable/mac_activate_manager_page.py",
                                     "c0d14590c9e4febe3a1c2470ba59814b15c7052bc1e06904de3c33fda8478fbc"),
    "mac_install_agent.py": ("remote-development/mac_install_agent.py",
                             "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"),
}


def main():
    if sys.platform != "darwin" or len(sys.argv) != 1:
        raise ValueError("Cette activation est réservée au Mac Rap Brain.")
    with tempfile.TemporaryDirectory(prefix="rapbrain-open-page-") as directory:
        root = Path(directory)
        for filename, (path, digest) in FILES.items():
            url = BASE + path
            with urllib.request.urlopen(url, timeout=20) as response:
                raw = response.read(100_001)
                if response.geturl() != url:
                    raise ValueError("Source de mise à niveau inattendue.")
            if len(raw) > 100_000 or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("Empreinte de mise à niveau inattendue.")
            (root / filename).write_bytes(raw)
        result = subprocess.run([sys.executable, str(root / "mac_activate_manager_page.py")],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ValueError(result.stderr.strip() or "Activation refusée.")
        print(result.stdout.strip())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
