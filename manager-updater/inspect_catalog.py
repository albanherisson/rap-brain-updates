#!/usr/bin/env python3
"""Rap Brain Manager stable-catalog inspector. VERIFICATION ONLY; NEVER INSTALLS."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit
from zip_gate import verify_zip, UnsafeArchive
from strict_json import parse_signed_json, InvalidSignedJSON

PINNED_PUBLISHER_KEY = "LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY="
MAX_CATALOG_BYTES = 65536
MAX_ARCHIVE_BYTES = 250 * 1024 * 1024
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HASH = re.compile(r"^[0-9a-f]{64}$")
ARCHIVE = re.compile(r"^Rap_Brain_Manager_[A-Za-z0-9._-]+\.zip$")


class Reject(Exception):
    pass


def check_catalog_bytes(raw, archive_path=None, verifier=None):
    if not 0 < len(raw) <= MAX_CATALOG_BYTES:
        raise Reject("Catalog size outside bounds")
    try:
        envelope = parse_signed_json(raw)
    except InvalidSignedJSON as exc:
        raise Reject("Invalid or ambiguous signed JSON catalog") from exc
    if type(envelope) is not dict or set(envelope) != {"payload", "signature"}:
        raise Reject("Unexpected envelope fields")
    payload, signature = envelope["payload"], envelope["signature"]
    if type(payload) is not dict or set(payload) != {"schema", "channel", "product", "version", "archive", "install_allowed"}:
        raise Reject("Unexpected payload fields")
    if payload["schema"] != 1 or type(payload["schema"]) is not int:
        raise Reject("Unsupported schema")
    if payload["channel"] != "manager-stable" or payload["product"] != "Rap Brain Manager":
        raise Reject("Wrong channel or product")
    if payload["install_allowed"] is not False:
        raise Reject("Installation is DISABLED pending rollback validation")
    if type(payload["version"]) is not str or not VERSION.fullmatch(payload["version"]):
        raise Reject("Bad version")
    info = payload["archive"]
    if type(info) is not dict or set(info) != {"filename", "size", "sha256", "url"}:
        raise Reject("Unexpected archive fields")
    if type(info["filename"]) is not str or not ARCHIVE.fullmatch(info["filename"]):
        raise Reject("Bad archive filename")
    if type(info["size"]) is not int or not 0 < info["size"] <= MAX_ARCHIVE_BYTES:
        raise Reject("Archive size outside bounds")
    if type(info["sha256"]) is not str or not HASH.fullmatch(info["sha256"]):
        raise Reject("Bad SHA256")
    if type(info["url"]) is not str:
        raise Reject("Missing archive URL")
    uri = urlsplit(info["url"])
    if uri.scheme != "https" or uri.username or uri.password or uri.fragment or uri.query or uri.port is not None:
        raise Reject("Unsafe archive URL")
    # Avoid cross-site redirects: real downloader must independently enforce host/redirect policy.
    if uri.hostname not in {"github.com", "albanherisson.github.io"}:
        raise Reject("Untrusted archive host")
    if uri.hostname == "github.com" and not uri.path.startswith("/albanherisson/rap-brain-updates/releases/download/"):
        raise Reject("Archive must originate from the official repository")
    if uri.hostname == "albanherisson.github.io" and not uri.path.startswith("/rap-brain-updates/"):
        raise Reject("Archive must originate from the official Pages path")
    if not uri.path.endswith("/" + info["filename"]):
        raise Reject("Archive URL name mismatch")
    if not isinstance(signature, str):
        raise Reject("Missing signature")
    try:
        sig = base64.b64decode(signature, validate=True)
    except ValueError as exc:
        raise Reject("Malformed signature") from exc
    if len(sig) != 64:
        raise Reject("Bad signature length")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if verifier is not None:
        verifier(signature, canonical)
    else:
        with tempfile.TemporaryDirectory(prefix="rapbrain_verify_") as directory:
            target = Path(directory) / "payload.json"
            target.write_bytes(canonical)
            try:
                completed = subprocess.run(
                    ["/usr/bin/swift", str(Path(__file__).with_name("verify_envelope.swift")), signature, str(target)],
                    capture_output=True, text=True, timeout=120, check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise Reject("Signature verifier unavailable") from exc
            if completed.returncode:
                raise Reject("Publisher signature rejected: " + completed.stderr.strip()[:200])
    if archive_path is not None:
        archive_path = Path(archive_path)
        if archive_path.is_symlink() or not archive_path.is_file() or archive_path.name != info["filename"]:
            raise Reject("Archive path mismatch")
        if archive_path.stat().st_size != info["size"]:
            raise Reject("Archive size mismatch")
        sha = hashlib.sha256()
        with archive_path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                sha.update(block)
        if sha.hexdigest() != info["sha256"]:
            raise Reject("Archive digest mismatch")
        try:
            verify_zip(archive_path)
        except UnsafeArchive as exc:
            raise Reject("Archive content rejected: " + str(exc)) from exc
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--archive", type=Path, required=True, help="Required local ZIP for integrity verification; never unpacked")
    args = parser.parse_args()
    try:
        payload = check_catalog_bytes(args.catalog.read_bytes(), args.archive)
    except (Reject, OSError, UnicodeError, ValueError) as exc:
        parser.exit(1, "REJECT: " + str(exc) + "\n")
    print("VERIFIED SIGNATURE AND ARCHIVE HASH (READ-ONLY):", payload["product"], payload["version"])
    print("No files downloaded, installed, replaced or executed.")


if __name__ == "__main__":
    main()
