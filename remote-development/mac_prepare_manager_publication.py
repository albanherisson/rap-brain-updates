#!/usr/bin/env python3
"""Sign Manager release 14 on the publisher Mac and rehearse it on copies."""

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request


REPO = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
HANDOFF_URL = (REPO + "cdb675c3b28ae30f619833fd71490564b630fae2"
               "/remote-development/mac_manager_handoff_trial.py")
HANDOFF_SHA = "c68d0c9d85a4f82e9d9caf9ef4970fe40bed84098f9b3005d591b62d9bc6b783"
SIGNER_URL = (REPO + "39a5718e93d3f9520b4cdeab105cdf7e3f332161"
              "/manager-updater/finish_candidate/mac_sign_manager_finish.py")
SIGNER_SHA = "a2b5e388ed2b9c7aebb51b7971fef9092c60f7f2bea6ce4fd49b9efe905acba4"
CHANNEL = REPO + "main/manager-stable/manifest.json"
CHANNEL_SHA = "68de2a9d0daa76486cb9e68c2a5e3f80b3ec2ce93c6c560950849a5c4ac15b2b"
ARCHIVE_PATH = "manager-stable/update-14.zip"
ARCHIVE_URL = REPO + "main/" + ARCHIVE_PATH
OUTPUT = "RapBrain_Manager_Update_14_Candidate.zip"
KEY_PATH = Path("Library/Application Support/RapBrainManager/publisher_ed25519.key")
SEQUENCE = 14
PILL = '<span class="pill" id="updatepill">'
STARTUP = "(async()=>{await refreshStatus();"
OUTCOME = """async function refreshUpdateOutcome(){
  try{
    const result=await get('/api/rapbrain/manager-update-state');
    if($('updatelog').textContent!=='Aucune vérification demandée.')return;
    const outcomes=new Map([
      ['committed',['Mise à jour installée','Mise à jour signée installée. Le contrôle du serveur a réussi.','yes']],
      ['rolled_back',['Version précédente restaurée','La version précédente a été restaurée. Le serveur a redémarré.','warn']],
      ['restored_stopped',['Version restaurée, serveur arrêté','La version précédente a été restaurée. Le serveur reste arrêté.','warn']],
      ['aborted',['Mise à jour interrompue','La mise à jour a été interrompue avant l’installation.','warn']],
      ['check_required',['Vérification requise','Vérifie l’état de la dernière mise à jour avant de réessayer.','warn']]
    ]);
    if(result?.state==='committed'&&result.installation_performed!==true)return;
    const outcome=outcomes.get(result?.state);
    if(!outcome)return;
    const [label,message,style]=outcome;
    $('updatepill').textContent=label;
    $('updatepill').className='pill '+style;
    write('updatelog',message);
  }catch(e){}
}
void refreshUpdateOutcome();
"""


def require(condition, error):
    if not condition:
        raise ValueError(error)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fetch_pinned(url, digest, limit):
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(limit + 1)
        require(response.geturl() == url and 0 < len(raw) <= limit, "publisher_download_changed")
    require(sha(raw) == digest, "publisher_input_hash_changed")
    return raw


def load_module(path, code):
    path.write_bytes(code)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dashboard_candidate(raw, expected):
    require(sha(raw) == expected, "publisher_dashboard_baseline_changed")
    text = raw.decode("utf-8")
    require(text.count(PILL) == text.count(STARTUP) == 1, "publisher_dashboard_anchor_changed")
    return text.replace(PILL, '<span class="pill" id="updatepill" aria-live="polite">', 1).replace(
        STARTUP, OUTCOME + STARTUP, 1).encode("utf-8")


def create_release(dashboard, support, signer, key, now):
    from manager_update_release import verify_archive, verify_manifest

    payload = dashboard_candidate(dashboard, support.DASHBOARD_SHA)
    archive = signer.public_zip({support.MEMBER: payload})
    manifest = {
        "schema": "rapbrain-manager-production-v1",
        "sequence": SEQUENCE,
        "issued_at": now - 1,
        "expires_at": now + 14 * 86400,
        "production_install_authorized": True,
        "data_migrations": [],
        "validation": {"macos_copy_install": "passed", "rollback": "passed", "runtime": "passed"},
        "files": [{"path": support.MEMBER, "baseline_sha256": support.DASHBOARD_SHA,
                   "payload_sha256": sha(payload)}],
        "required_server_sha256": support.SERVER_SHA,
        "archive_url": ARCHIVE_URL,
        "archive_sha256": sha(archive),
        "archive_bytes": len(archive),
    }
    public, signature = signer.sign(key, signer.canonical(manifest))
    envelope = signer.canonical({
        "signed_payload": manifest,
        "signature_algorithm": "Ed25519",
        "public_key_base64": base64.b64encode(public).decode("ascii"),
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    })
    accepted = verify_manifest(envelope, minimum_sequence=SEQUENCE - 1, now=now)
    require(accepted == manifest and verify_archive(archive, accepted) == {support.MEMBER: payload},
            "publisher_signature_or_archive_invalid")
    return envelope, archive, payload, sha(public)


def helper_matches(home, state_path, tested):
    active = home / state_path / "helper"
    if not active.is_dir() or active.resolve() != active:
        return False
    expected = {path.name: sha(path.read_bytes()) for path in tested.iterdir()}
    try:
        present = {path.name for path in active.iterdir()}
        if present != set(expected) | {"signed-manifest.json"}:
            return False
        for name, digest in expected.items():
            path = active / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 250_000:
                return False
            if sha(path.read_bytes()) != digest:
                return False
    except OSError:
        return False
    return True


def export_package(path, contents):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".rapbrain-publication-") as temp:
        temp.write(contents)
        temp.flush()
        os.fsync(temp.fileno())
        os.link(temp.name, path)


def prepare(home, root):
    output = home / "Downloads" / OUTPUT
    require(output.parent.resolve() == output.parent and output.parent.is_dir(),
            "publisher_download_folder_invalid")
    require(not os.path.lexists(output), "publisher_candidate_already_exists")
    # Bind the new sequence to the observed stable channel before signing.
    fetch_pinned(CHANNEL, CHANNEL_SHA, 65_536)
    handoff = load_module(root / "handoff_runner.py", fetch_pinned(HANDOFF_URL, HANDOFF_SHA, 50_000))
    signer = load_module(root / "publisher_signer.py", fetch_pinned(SIGNER_URL, SIGNER_SHA, 25_000))
    (root / "trial_support.py").write_bytes(fetch_pinned(handoff.SUPPORT_URL, handoff.SUPPORT_SHA, 50_000))
    support = handoff.load_support(root)
    helper_zip = support.fetch_helper()
    backup = support.fetch_bytes(support.BACKUP_URL, 20_000)
    locale = {}
    locale_code = fetch_pinned(handoff.LOCALE_URL, handoff.LOCALE_SHA, 20_000)
    exec(compile(locale_code, "locale_candidate.py", "exec"), locale)
    click = handoff.click_in_webkit(root)
    signed_candidate = None

    def signed_trial(dashboard, _branch):
        nonlocal signed_candidate
        if signed_candidate is None:
            # The verified bytes stay private to the temporary workspace until both trials pass.
            signed_candidate = create_release(dashboard, support, signer, home / KEY_PATH,
                                              int(time.time()))
        else:
            require(dashboard_candidate(dashboard, support.DASHBOARD_SHA) == signed_candidate[2],
                    "publisher_rehearsal_baseline_changed")
        return signed_candidate

    print("Candidat Manager 14 : signature locale et essai sur copies", flush=True)
    support.signed_trial = signed_trial
    evidence = handoff.run_trial(home, root, support, helper_zip, backup, locale, click)
    require(evidence["status"] == "pass" and signed_candidate is not None, "publisher_rehearsal_failed")
    envelope, archive, _payload, pin = signed_candidate
    from bootstrap_release import PUBLISHER_PIN
    require(pin == PUBLISHER_PIN, "publisher_pin_mismatch")
    fetch_pinned(CHANNEL, CHANNEL_SHA, 65_536)
    package = signer.public_zip({"manager-stable/manifest.json": envelope, ARCHIVE_PATH: archive})
    report = {"status": "pass", "sequence": SEQUENCE, "publisher_signature": "verified",
              "copy_install": evidence["copy_install"], "copy_rollback": evidence["copy_rollback"],
              "macos_codesign": evidence["macos_codesign"], "real_server_health": evidence["real_server_health"],
              "synthetic_sqlite_and_config": evidence["synthetic_sqlite_and_config"],
              "active_helper_code_matches_copy": helper_matches(home, handoff.STATE_PATH, root / "dependencies"),
              "zip_sha256": sha(package), "zip": output.name}
    export_package(output, package)
    return report


def main():
    require(sys.platform == "darwin" and len(sys.argv) == 1, "publisher_macos_required")
    with tempfile.TemporaryDirectory(prefix="rapbrain-manager-publication-") as temporary:
        report = prepare(Path.home().resolve(), Path(temporary).resolve())
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        detail = str(error)
        print(json.dumps({"status": "failed", "reason": detail if re.fullmatch(
            r"[a-zA-Z0-9_]+", detail) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
