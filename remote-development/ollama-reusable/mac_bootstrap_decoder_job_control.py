#!/usr/bin/env python3
"""Download the reviewed bridge package by commit and hash before activation."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request


COMMIT = "3f523e06079a36a8b484409e612a0535959f45eb"
BASE = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/" + COMMIT + "/"
FILES = {
    "mac_bridge.py": ("remote-development/ollama-reusable/mac_bridge.py",
                      "95bca2af77d0f940e2684d65b8cf6b7b788b0140790217d064a83fbca5ec7961"),
    "mac_decoder_track_status_request.py":
        ("remote-development/ollama-reusable/mac_decoder_track_status_request.py",
         "0ba5b71e62515b37c0191ac59d354e78ce3ecdd6ee4a0dd051dcc129389c085b"),
    "mac_decoder_job_action_request.py":
        ("remote-development/ollama-reusable/mac_decoder_job_action_request.py",
         "206d34fce79b6f0b0c7437f540abf7868e7cac181e4b335d7765e7abe477a36c"),
    "mac_activate_decoder_job_control.py":
        ("remote-development/ollama-reusable/mac_activate_decoder_job_control.py",
         "e9a7daed402a6ba807e7c94e90e1b974919b9c9ce6ec6fea9f03ea9264cd4193"),
    "mac_install_agent.py": ("remote-development/mac_install_agent.py",
                             "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"),
}


def main():
    if sys.platform != "darwin" or len(sys.argv) != 1:
        raise ValueError("Activation réservée au Mac Rap Brain.")
    with tempfile.TemporaryDirectory(prefix="rapbrain-decoder-job-control-") as directory:
        root = Path(directory)
        for filename, (path, digest) in FILES.items():
            url = BASE + path
            with urllib.request.urlopen(url, timeout=20) as response:
                content = response.read(100_001)
                if response.geturl() != url:
                    raise ValueError("Source inattendue.")
            if len(content) > 100_000 or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("Empreinte inattendue.")
            (root / filename).write_bytes(content)
        result = subprocess.run([sys.executable, str(root / "mac_activate_decoder_job_control.py")],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ValueError(result.stderr.strip() or "Activation refusée.")
        print(result.stdout.strip())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
