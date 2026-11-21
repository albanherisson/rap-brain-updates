#!/usr/bin/env python3
"""Fetch pinned private-track bridge files and activate them on the Mac."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request


COMMIT = "781c2dce1f39118d2a968000808a5c288b83c4b6"
BASE = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/" + COMMIT + "/"
FILES = {
    "mac_bridge.py": ("remote-development/ollama-reusable/mac_bridge.py",
                      "ef84af6ff96c604c5a93206ad4b7fef082816c7d81f269c518c2382db23f3450"),
    "mac_decoder_track_status_request.py": ("remote-development/ollama-reusable/mac_decoder_track_status_request.py",
                                            "b2224b1ff9321d16e94070a9b13a9f81cd6c73ee42bb872013ff9272aa309026"),
    "mac_decoder_queue_request.py": ("remote-development/ollama-reusable/mac_decoder_queue_request.py",
                                     "a57b0b096f45d7620c8c5ee4ae1e19d114b48c760d38fdfcacf24b11e4deea16"),
    "mac_activate_decoder_track_queue.py": ("remote-development/ollama-reusable/mac_activate_decoder_track_queue.py",
                                            "67cba8f86250188beee54711fee201b8a5967adc856f28fbea0f279ca321ab78"),
    "mac_install_agent.py": ("remote-development/mac_install_agent.py",
                             "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"),
}


def main():
    if sys.platform != "darwin" or len(sys.argv) != 1:
        raise ValueError("Cette activation est réservée au Mac Rap Brain.")
    with tempfile.TemporaryDirectory(prefix="rapbrain-decoder-track-") as directory:
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
        result = subprocess.run([sys.executable, str(root / "mac_activate_decoder_track_queue.py")],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ValueError(result.stderr.strip() or "Activation refusée.")
        print(result.stdout.strip())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
