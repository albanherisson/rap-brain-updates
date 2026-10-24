#!/usr/bin/env python3
"""Prepare a NON-INSTALLABLE signed update candidate. Never uploads private keys."""
import argparse, base64, hashlib, json, pathlib, re, subprocess, tempfile
from urllib.parse import urlsplit
p=argparse.ArgumentParser()
p.add_argument("--archive",required=True,type=pathlib.Path)
p.add_argument("--version",required=True)
p.add_argument("--url",required=True)
p.add_argument("--output",required=True,type=pathlib.Path)
a=p.parse_args()
if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?",a.version): p.error("Version X.Y.Z requise")
if not a.archive.is_file() or a.archive.is_symlink() or not re.fullmatch(r"Rap_Brain_Manager_[A-Za-z0-9._-]+\.zip",a.archive.name): p.error("Archive Manager invalide")
u=urlsplit(a.url)
if u.scheme!="https" or u.hostname not in ("github.com","albanherisson.github.io","objects.githubusercontent.com") or u.username or u.password or u.fragment: p.error("Hébergement HTTPS non approuvé")
content=a.archive.read_bytes()
payload={"schema":1,"channel":"manager-stable","product":"Rap Brain Manager","version":a.version,"archive":{"filename":a.archive.name,"size":len(content),"sha256":hashlib.sha256(content).hexdigest(),"url":a.url},"install_allowed":False}
canonical=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()
with tempfile.TemporaryDirectory() as t:
    path=pathlib.Path(t)/"signed-payload.json";path.write_bytes(canonical)
    result=subprocess.run(["/usr/bin/swift",str(pathlib.Path(__file__).with_name("publisher_key.swift")),"sign",str(path)],capture_output=True,text=True,timeout=120,check=True)
signature=result.stdout.strip()
if len(base64.b64decode(signature,validate=True))!=64: raise ValueError("Invalid Ed25519 signature")
a.output.write_text(json.dumps({"payload":payload,"signature":signature},ensure_ascii=False,indent=2)+"\n")
print("Candidat signé généré ; aucune installation autorisée.",a.output)
