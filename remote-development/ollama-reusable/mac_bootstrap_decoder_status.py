#!/usr/bin/env python3
"""Download pinned bridge status files and activate them on the Rap Brain Mac."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request


COMMIT = "3fe9076405b29ca7d1230d6798101f7d6fc47f06"
BASE = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/" + COMMIT + "/"
FILES = {
    "mac_bridge.py": ("remote-development/ollama-reusable/mac_bridge.py",
                      "263f5a9397dc07d90735aa46c490c70ce39fa955a73cc28f2b30858ca6feb856"),
    "mac_decoder_status_request.py": ("remote-development/ollama-reusable/mac_decoder_status_request.py",
                                     "893834499e87cc1c9f054286646212f108cf076ae429a37a116d7b83fac0e59b"),
    "mac_manager_page_request.py": ("remote-development/ollama-reusable/mac_manager_page_request.py",
                                    "1740fa3c44febb2be2949efe20d1e1a33c1fbd3118ecf49bcc657725703eff23"),
    "mac_activate_decoder_status.py": ("remote-development/ollama-reusable/mac_activate_decoder_status.py",
                                       "9bb92156c21d034d4b2e1c75079064d25f58fba334527b94c4ce78a1dc9800a3"),
    "mac_install_agent.py": ("remote-development/mac_install_agent.py",
                             "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"),
}


def main():
    if sys.platform != "darwin" or len(sys.argv) != 1:
        raise ValueError("Cette activation est réservée au Mac Rap Brain.")
    with tempfile.TemporaryDirectory(prefix="rapbrain-decoder-status-") as directory:
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
        result = subprocess.run([sys.executable, str(root / "mac_activate_decoder_status.py")],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ValueError(result.stderr.strip() or "Activation refusée.")
        print(result.stdout.strip())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
