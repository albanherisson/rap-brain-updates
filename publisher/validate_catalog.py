#!/usr/bin/env python3
"""Offline verification of an informational, NON-INSTALLABLE candidate catalog."""
import argparse
import base64
import hashlib
import json
import pathlib
import subprocess
import tempfile

p=argparse.ArgumentParser()
p.add_argument("--catalog",required=True,type=pathlib.Path)
p.add_argument("--public-key",required=True)
p.add_argument("--archive",required=True,type=pathlib.Path)
a=p.parse_args()
def fail(msg): p.error(msg)
doc=json.loads(a.catalog.read_text())
if sorted(doc)!=["payload","signature"]: fail("catalog fields unexpected")
body=doc["payload"]
if not isinstance(body,dict) or body.get("schema")!=1 or body.get("product")!="Rap Brain Manager" or body.get("install_allowed") is not False: fail("Not an approved NON-INSTALLABLE catalog")
info=body.get("archive")
if not isinstance(info,dict): fail("missing archive metadata")
if info.get("filename")!=a.archive.name or a.archive.is_symlink() or not a.archive.is_file(): fail("archive name or path mismatch")
try:
    if len(base64.b64decode(a.public_key,validate=True))!=32: fail("invalid public key")
    if len(base64.b64decode(doc["signature"],validate=True))!=64: fail("invalid signature")
except Exception: fail("bad base64 key/signature")
encoded=json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode("utf-8")
with tempfile.TemporaryDirectory() as temp:
    source=pathlib.Path(temp)/"payload.json"
    source.write_bytes(encoded)
    cp=subprocess.run(["/usr/bin/swift",str(pathlib.Path(__file__).with_name("verify_signature.swift")),a.public_key,doc["signature"],str(source)],capture_output=True,text=True,timeout=180)
    if cp.returncode: fail("Ed25519 signature rejected: "+(cp.stderr or cp.stdout).strip()[:250])
archive=a.archive.read_bytes()
if len(archive)!=info.get("size") or hashlib.sha256(archive).hexdigest()!=info.get("sha256"): fail("archive differs from signed metadata")
print("✅ Offline signed catalog and archive verified. No installation permitted.")
