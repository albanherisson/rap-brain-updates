#!/usr/bin/env python3
"""Read-only production-key signature and archive inspection on Mac. NEVER installs."""
import base64
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import zipfile

PUBLIC_KEY_B64 = "LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY="
EXPECTED_ARCHIVE_SHA256 = "6f9225d9bb4c12fb200c9bc0074240bf80cbe48648db8a6049d018eddaebc9b7"
EXPECTED_MANAGER_SHA256 = "bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
ROOT = Path.home() / "Library/Application Support/RapBrainManager/isolated-dryrun"
CANDIDATE = ROOT / "publisher-signed-candidate-1.0.6"
CATALOG = CANDIDATE / "catalog.json"
ARCHIVE = CANDIDATE / "Rap_Brain_Manager_1.0.6.zip"
ENTRY = "Contents/Resources/manager.py"
SWIFT = r'''import Foundation
import CryptoKit
let keyB64 = "LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY="
func fail(_ s: String) -> Never { fputs("REFUS: \\(s)\\n", stderr); exit(1) }
let a = CommandLine.arguments
guard a.count == 3 else { fail("arguments invalides") }
guard let kd = Data(base64Encoded:keyB64), kd.count == 32,
      let key = try? Curve25519.Signing.PublicKey(rawRepresentation:kd),
      let sig = Data(base64Encoded:a[1]), sig.count == 64,
      let data = try? Data(contentsOf:URL(fileURLWithPath:a[2])) else { fail("entrée invalide") }
guard key.isValidSignature(sig, for:data) else { fail("signature rejetée") }
print("SIGNATURE_OK")
'''

def refuse(message):
    raise ValueError(message)

def safe_file(p, maxbytes):
    st=p.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size > maxbytes:
        refuse("Unsafe or oversized file: " + p.name)
    return p.read_bytes()

def verify(signature, message):
    with tempfile.TemporaryDirectory(prefix="rapbrain-readonly-") as temp:
        temp=Path(temp)
        swift=temp/"verify.swift"
        data=temp/"signed.json"
        swift.write_text(SWIFT)
        data.write_bytes(message)
        result=subprocess.run(["/usr/bin/swift",str(swift),signature,str(data)],
                capture_output=True,text=True,timeout=120,check=False)
        return result.returncode == 0 and "SIGNATURE_OK" in result.stdout

def main():
    if not ROOT.is_dir() or ROOT.is_symlink() or not CANDIDATE.is_dir() or CANDIDATE.is_symlink():
        refuse("Candidate directory missing or unsafe")
    raw=safe_file(CATALOG,65536)
    catalog=json.loads(raw)
    if type(catalog) is not dict or set(catalog)!={"payload","signature"}:
        refuse("Unexpected catalog fields")
    payload=catalog["payload"]
    if type(payload) is not dict or set(payload)!={"schema","channel","product","version","install_allowed","archive"}:
        refuse("Unexpected signed payload fields")
    if payload["schema"] != 1 or type(payload["schema"]) is not int or payload["channel"]!="manager-stable" or payload["product"]!="Rap Brain Manager" or payload["version"]!="1.0.6" or payload["install_allowed"] is not False:
        refuse("Invalid product, version, schema or installation protection")
    meta=payload["archive"]
    if type(meta) is not dict or set(meta)!={"filename","size","sha256","url"}:
        refuse("Unexpected archive metadata")
    if meta["filename"]!=ARCHIVE.name or meta["url"]!="https://github.com/albanherisson/rap-brain-updates/releases/download/lab-1.0.6/"+ARCHIVE.name:
        refuse("Unexpected filename or source URL")
    zip_bytes=safe_file(ARCHIVE,250*1024*1024)
    actual_sha=hashlib.sha256(zip_bytes).hexdigest()
    if actual_sha!=EXPECTED_ARCHIVE_SHA256 or actual_sha!=meta["sha256"] or len(zip_bytes)!=meta["size"]:
        refuse("Archive hash or size mismatch")
    with zipfile.ZipFile(ARCHIVE,"r") as z:
        names=z.namelist()
        if names != [ENTRY]: refuse("Unexpected ZIP layout")
        member=z.getinfo(ENTRY)
        if member.file_size>2_000_000 or member.flag_bits & 1:
            refuse("Oversized or encrypted ZIP member")
        extracted=z.read(ENTRY)
        if hashlib.sha256(extracted).hexdigest()!=EXPECTED_MANAGER_SHA256:
            refuse("Manager payload fingerprint mismatch")
    canonical=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode("utf-8")
    signature=catalog["signature"]
    if not isinstance(signature,str) or len(base64.b64decode(signature,validate=True))!=64:
        refuse("Signature encoding is invalid")
    if not verify(signature,canonical): refuse("Signature verification failed")
    print("OK: signature réelle du catalogue vérifiée avec CryptoKit")
    if verify(signature, canonical+b" "):
        refuse("Mutated catalog incorrectly accepted")
    print("OK: catalogue modifié refusé")
    print("OK: archive ZIP intègre, contenu reconnu, installation interdite")
    print("OK: aucune application modifiée ni lancée")

if __name__=="__main__":
    try: main()
    except (ValueError,OSError,subprocess.TimeoutExpired,zipfile.BadZipFile,KeyError,TypeError) as e:
        print("ECHEC:",str(e),file=sys.stderr)
        raise SystemExit(1)
