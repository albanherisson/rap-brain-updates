#!/usr/bin/env python3
"""Assemble NON-INSTALLABLE lab catalog from a detached Ed25519 signature.
Does not access private key, execute installed code, install or publish anything.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

EXPECTED_CHANNEL="manager-stable"
EXPECTED_PRODUCT="Rap Brain Manager"

def assemble(raw:bytes, signature_text:str, archive:bytes, filename:str):
    if len(raw)>65536 or not raw:
        raise ValueError("Canonical payload too large or empty")
    if type(signature_text) is not str:
        raise ValueError("Missing detached signature")
    try:
        sig=base64.b64decode(signature_text.strip(),validate=True)
    except (ValueError,base64.binascii.Error) as exc:
        raise ValueError("Invalid detached signature") from exc
    if len(sig)!=64:
        raise ValueError("Wrong detached signature size")
    try:
        from strict_json import parse_signed_json
        payload=parse_signed_json(raw)
    except Exception as exc:
        raise ValueError("Invalid signed payload") from exc
    if not isinstance(payload,dict) or set(payload)!={"schema","channel","product","version","install_allowed","archive"}:
        raise ValueError("Unexpected payload fields")
    if payload["channel"]!=EXPECTED_CHANNEL or payload["product"]!=EXPECTED_PRODUCT or payload["install_allowed"] is not False:
        raise ValueError("Wrong product or install flag")
    canonical=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()
    if raw!=canonical:
        raise ValueError("Payload must be exact canonical JSON bytes")
    info=payload["archive"]
    if not isinstance(info,dict) or set(info)!={"filename","size","sha256","url"}:
        raise ValueError("Bad ZIP metadata")
    if info["filename"]!=filename or info["size"]!=len(archive) or info["sha256"]!=hashlib.sha256(archive).hexdigest():
        raise ValueError("Archive differs from payload")
    return {"payload":payload,"signature":signature_text.strip()}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--signature",required=True,help="Detached PUBLIC signature (base64), not private key")
    a=p.parse_args()
    root=a.root.expanduser()
    expected=Path.home()/"Library/Application Support/RapBrainManager/isolated-dryrun/distinct-unsigned-lab-1.0.6"
    if root!=expected or root.is_symlink() or not root.is_dir():
        p.error("Only the exact non-installable lab directory is permitted")
    output=root/"catalog.json"
    if output.exists() or output.is_symlink():
        p.error("Refusing to overwrite catalog")
    raw=(root/"canonical_payload.json").read_bytes()
    archive=(root/"Rap_Brain_Manager_1.0.6_lab_distinct.zip").read_bytes()
    doc=assemble(raw,a.signature,archive,"Rap_Brain_Manager_1.0.6_lab_distinct.zip")
    with output.open("x",encoding="utf-8") as f:
        json.dump(doc,f,sort_keys=True,ensure_ascii=False,indent=2)
        f.write("\n")
    print("OK: detached signature attached to non-installable lab catalog")
    print("NOTE: signature has NOT yet been cryptographically verified; use pinned CryptoKit verifier")
    print("No application changed; no private key accessed")

if __name__=="__main__":
    try:main()
    except (OSError,ValueError) as exc:
        print("REFUS:",str(exc),file=sys.stderr)
        raise SystemExit(1)
