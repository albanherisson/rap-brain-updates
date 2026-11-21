#!/usr/bin/env python3
"""Fetch pinned public bridge files and activate the fixed Rap Brain page action."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request


COMMIT = "ffc48a23335aad35de0db8ae2267328012ad6f7c"
BASE = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/" + COMMIT + "/"
FILES = {
    "mac_bridge.py": ("remote-development/ollama-reusable/mac_bridge.py",
                      "48d35d666bd540fb0da179a3d8300ce25b1f232d3cf8a5f28f5b670ba60344a1"),
    "mac_manager_page_request.py": ("remote-development/ollama-reusable/mac_manager_page_request.py",
                                    "1740fa3c44febb2be2949efe20d1e1a33c1fbd3118ecf49bcc657725703eff23"),
    "mac_activate_manager_page.py": ("remote-development/ollama-reusable/mac_activate_manager_page.py",
                                     "60337ee6401d60f5ac91a2a27d47b4fbeda8edc20b276311c706f78a3733afb4"),
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
