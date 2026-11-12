"""Sign an approved dashboard or decoder release after isolated Mac trials."""

import base64
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

from mac_private_source_trial import github_file, keychain_token, trial_commit
from manager_remote_request import decode_remote_json, read_remote_json

REPO = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
PREPARER = REPO + "9f016488aea8679054836930607de4c29265524f/remote-development/mac_prepare_manager_e2e_17.py"
PREPARER_SHA = "1178b2f9aafd6dd04f77c8c8add9201750b7b0f46a3d31097efa06bc43295183"
BUTTON = REPO + "964665a91aeaca13719782d6a52b8ac8ba7c937d/remote-development/mac_manager_remote_update_trial.py"
BUTTON_SHA = "495ce0989ed8fd98cb317ef37ac6923ffee5fc1aefad9ff06245c0ac2a5fac9c"
HELPER_TREE = "c061e4eedaf4415c5ed2c711053d4a7329faf83033ca03322468302f2cf9aca2"
APP = Path("Downloads/RapBrainManager_App_Beta14/Rap Brain Manager Beta 14.app")
STATE = Path("Downloads/RapBrainManagerBackups/secure-update")
SOURCE = Path("Downloads/rap-brain")
KEY = Path("Library/Application Support/RapBrainManager/publisher_ed25519.key")
LAUNCHER = "642dc6d2595cca8f5ad6a189dc7362cca74080344beb9e9c331880b157869c7e"
MEMBER = "app/dashboard_beta14.html"
SERVER_MEMBER = "server.py"
DECODER_SERVER_SHA = "1238354b0aaf5ed3ac92c4c4ddddf33b80a22212a9dc6ac8d450f217eaff2e32"
DECODER_TEST = "rap_brain/tests/test_decoder_memory.py"
DECODER_TEST_SHA = "039e855c9843cbfff725b4f9fb45031dd6c537174cc2c6bfc422f2051ec20243"
CHANNEL = REPO + "main/manager-stable/manifest.json"
VALIDATION = {"macos_copy_install": "passed", "rollback": "passed", "runtime": "passed"}
NOTICE = re.compile(r"(?<=\['committed',\['Mise à jour installée',')[A-Za-zÀ-ÖØ-öø-ÿ0-9 .,!?-]{1,160}(?=','yes'\]\])")
HEX = re.compile(r"[0-9a-f]{64}\Z")
FIELDS = {"schema", "id", "sequence", "archive_sha256",
          "baseline_dashboard_sha256", "stable_manifest_sha256", "expected_server_sha256",
          "issued_at", "expires_at"}
DASHBOARD_HASHES = {"candidate_dashboard_sha256"}
DECODER_HASHES = {"candidate_server_sha256", "source_manifest_sha256"}
DASHBOARD_GRANT = "rapbrain-manager-sign-dashboard-v1"
DECODER_GRANT = "rapbrain-manager-sign-decoder-v1"
SIGN_ACTIONS = {"manager_sign_dashboard": DASHBOARD_GRANT, "manager_sign_decoder": DECODER_GRANT}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def parse_sign_task(task, now=None, *, allow_expired=False):
    now = int(time.time()) if now is None else now
    require(type(task) is dict and type(task.get("action")) is str and task["action"] in SIGN_ACTIONS,
            "manager_sign_task_invalid")
    schema = SIGN_ACTIONS[task["action"]]
    hashes = DECODER_HASHES if schema == DECODER_GRANT else DASHBOARD_HASHES
    fields = FIELDS | hashes
    require(task.keys() == fields | {"action", "authorization_commit"}
            and task["schema"] == "rapbrain-remote-task-v4"
            and type(task["authorization_commit"]) is str
            and re.fullmatch(r"[0-9a-f]{40}", task["authorization_commit"])
            and type(task["id"]) is str and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", task["id"])
            and type(task["sequence"]) is int and task["sequence"] >= 2
            and all(type(task[name]) is str and HEX.fullmatch(task[name]) for name in
                    hashes | {"archive_sha256", "baseline_dashboard_sha256",
                              "stable_manifest_sha256", "expected_server_sha256"})
            and type(task["issued_at"]) is int and type(task["expires_at"]) is int
            and 0 <= task["issued_at"] <= now
            and task["issued_at"] < task["expires_at"] <= task["issued_at"] + 3600,
            "manager_sign_task_invalid")
    if schema == DECODER_GRANT:
        require(task["candidate_server_sha256"] == DECODER_SERVER_SHA, "manager_sign_decoder_unreviewed")
    require(allow_expired or now < task["expires_at"], "manager_sign_task_expired")
    return {key: task[key] for key in fields} | {"schema": schema}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("manager_sign_redirect_refused")


def private_file(path, token, commit):
    opener = urllib.request.build_opener(NoRedirect())
    return github_file(path, token, commit, opener=opener.open)


def authorize(task, grant, *, token=keychain_token, fetch=private_file):
    secret = token()
    prefix = "remote-development/manager-signing/" + grant["id"] + "/"
    commit = task["authorization_commit"]
    approved = decode_remote_json(fetch(prefix + "authorization.json", secret, commit))
    require(type(approved) is dict and approved.keys() == grant.keys()
            and all(type(approved[key]) is type(value) and approved[key] == value
                    for key, value in grant.items()),
            "manager_sign_private_authorization_mismatch")
    archive = fetch(prefix + "update.zip", secret, commit)
    require(0 < len(archive) <= 100_000 and sha(archive) == grant["archive_sha256"],
            "manager_sign_archive_hash_changed")
    return archive


def checked(path, limit):
    require(path.resolve() == path and path.is_file() and 0 < path.stat().st_size <= limit,
            "manager_sign_local_file_unsafe")
    return path.read_bytes()


def verified_helpers(home, root):
    live = home / STATE / "helper"
    require(live.resolve() == live and live.is_dir(), "manager_sign_helper_directory_unsafe")
    contents = {}
    for path in sorted(live.iterdir()):
        if path.name == "signed-manifest.json":
            continue
        require(re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*\.(py|swift)", path.name),
                "manager_sign_helper_member_unsafe")
        contents[path.name] = checked(path, 250_000)
    tree = sha("".join(f"{name} {sha(raw)}\n" for name, raw in contents.items()).encode())
    require(tree == HELPER_TREE, "manager_sign_helper_tree_changed")
    modules = root / "verified-helper"
    modules.mkdir(mode=0o700)
    for name, raw in contents.items():
        (modules / name).write_bytes(raw)
    return modules, contents


def get_pinned(url, expected, limit=65_536):
    with urllib.request.build_opener(NoRedirect()).open(url, timeout=25) as response:
        raw = response.read(limit + 1)
        require(response.geturl() == url and 0 < len(raw) <= limit and sha(raw) == expected,
                "manager_sign_download_changed")
    return raw


def load(path, source):
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate_notice(baseline, updated):
    try:
        old_text, new_text = baseline.decode("utf-8"), updated.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("manager_sign_dashboard_encoding") from exc
    old = list(NOTICE.finditer(old_text))
    new = list(NOTICE.finditer(new_text))
    require(len(old) == len(new) == 1 and old[0][0] != new[0][0]
            and old_text[:old[0].start()] + new[0][0] + old_text[old[0].end():] == new_text,
            "manager_sign_dashboard_notice_scope")


def envelope(manifest, public, signature, canonical):
    return canonical({"signed_payload": manifest, "signature_algorithm": "Ed25519",
                      "public_key_base64": base64.b64encode(public).decode("ascii"),
                      "signature_base64": base64.b64encode(signature).decode("ascii")})


def prepare_trial(root, helper, sequence, *, decoder=False):
    raw = get_pinned(PREPARER, PREPARER_SHA).decode("utf-8")
    require(raw.count("remote=True)") == 1 and raw.count('{"sequence":14}') == 1,
            "manager_sign_trial_anchor_changed")
    raw = raw.replace("remote=True)", "remote=False)").replace('{"sequence":14}',
                                                              '{"sequence":' + str(sequence - 1) + '}')
    preparer = load(root / "reviewed_preparer.py", raw.encode("utf-8"))
    _, runner, support = preparer.configure_harness(root, helper)
    if decoder:
        runner_path = root / "remote/handoff_runner.py"
        text = preparer.replace_once(
            runner_path.read_text(encoding="utf-8"),
            '(app / "Contents/Resources" / support.MEMBER.removeprefix("app/")).read_bytes() == payload',
            '(source / "server.py").read_bytes() == payload')
        rollback = '        require(inventory(app) == app_inventory, "handoff_rollback_bytes_changed")'
        text = preparer.replace_once(text, rollback, rollback +
                                     '\n        checked_bytes(source / "server.py", support.SERVER_SHA)')
        runner = load(runner_path, text.encode("utf-8"))
    button = load(root / "reviewed_button.py", get_pinned(BUTTON, BUTTON_SHA))
    return preparer, runner, support, button


def decoder_copy(home, grant, authorization_commit, candidate):
    model_path = home / SOURCE / "data/ollama_model.json"
    try:
        config = checked(model_path, 4096)
    except (OSError, ValueError):
        if os.path.lexists(model_path):
            raise
        config = None
    record = decode_remote_json(config) if config is not None else {"model": "qwen3:8b"}
    model = record.get("model") if type(record) is dict else None
    require(type(model) is str and re.fullmatch(r"[a-zA-Z0-9_.:/-]{1,120}", model),
            "decoder_ollama_model_invalid")

    def check(workspace, _manifest):
        path = workspace / DECODER_TEST
        require(sha(checked(path, 65_536)) == DECODER_TEST_SHA
                and checked(workspace / "rap_brain/server.py", 250_000) == candidate,
                "manager_sign_decoder_source_changed")
        env = {"HOME": str(workspace), "TMPDIR": str(workspace), "PATH": os.defpath}
        for arguments, timeout in (([], 30), (["--real-ollama", model], 410)):
            process = subprocess.run([sys.executable, "-I", "-B", str(path), *arguments],
                                     cwd=workspace, env=env, capture_output=True,
                                     stdin=subprocess.DEVNULL, timeout=timeout)
            if process.returncode:
                reason = "manager_sign_decoder_test_failed"
                if arguments and process.stderr:
                    try:
                        failure = decode_remote_json(process.stderr.splitlines()[-1]).get("reason")
                        if type(failure) is str and re.fullmatch(r"decoder_ollama_[a-z0-9_]{1,60}", failure):
                            reason = failure
                    except (ValueError, AttributeError):
                        pass
                raise ValueError(reason)
        proof = decode_remote_json(process.stdout)
        require(proof == {"real_ollama": "verified", "sqlite_and_config": "preserved"},
                "manager_sign_decoder_proof_invalid")
        return proof

    result = trial_commit(keychain_token(), authorization_commit, grant["source_manifest_sha256"],
                          grant["candidate_server_sha256"], fetch=private_file, home=home, check=check)
    require(checked(model_path, 4096) == config if config is not None else not os.path.lexists(model_path),
            "decoder_ollama_live_config_changed")
    return result["reviewed_test"]


def sign_candidate(home, root, grant, archive, authorization_commit=None):
    # All executable verifier dependencies are pinned to the reviewed helper
    # installed by repair 16, then copied to a private workspace.
    modules, members = verified_helpers(home, root)
    paths = sys.path[:]
    loaded = set(sys.modules)
    sys.path.insert(0, str(modules))
    try:
        return rehearse_and_sign(home, root, grant, archive, members, authorization_commit)
    finally:
        sys.path[:] = paths
        # A later request must reload these modules from its own temporary
        # directory, including the Swift verifier they locate beside themselves.
        for name in set(sys.modules) - loaded:
            origin = getattr(sys.modules[name], "__file__", None)
            if origin and Path(origin).is_relative_to(root):
                sys.modules.pop(name, None)


def rehearse_and_sign(home, root, grant, archive, members, authorization_commit):
    from manager_update_release import verify_archive, verify_baseline, verify_manifest

    source = home / SOURCE
    resources = home / APP / "Contents/Resources"
    accepted = read_remote_json(home / STATE / "manager-accepted.json")
    stable = verify_manifest(get_pinned(CHANNEL, grant["stable_manifest_sha256"]))
    require(stable["sequence"] == grant["sequence"] - 1 and accepted == {"sequence": stable["sequence"]},
            "manager_sign_sequence_changed")
    require(sha(checked(resources / "launch_manager.py", 250_000)) == LAUNCHER,
            "manager_sign_launcher_changed")
    baseline = checked(resources / "dashboard_beta14.html", 250_000)
    require(sha(baseline) == grant["baseline_dashboard_sha256"], "manager_sign_dashboard_baseline_changed")
    decoder = grant["schema"] == DECODER_GRANT
    member = SERVER_MEMBER if decoder else MEMBER
    baseline_hash = grant["expected_server_sha256"] if decoder else grant["baseline_dashboard_sha256"]
    payload_hash = grant["candidate_server_sha256"] if decoder else grant["candidate_dashboard_sha256"]
    manifest = {"schema": "rapbrain-manager-production-v1", "sequence": grant["sequence"],
        "issued_at": grant["issued_at"], "expires_at": grant["issued_at"] + 14 * 86400,
        "production_install_authorized": True, "data_migrations": [], "validation": VALIDATION,
        "files": [{"path": member, "baseline_sha256": baseline_hash, "payload_sha256": payload_hash}],
        "required_server_sha256": grant["expected_server_sha256"],
        "archive_url": REPO + f'main/manager-stable/update-{grant["sequence"]}.zip',
        "archive_sha256": grant["archive_sha256"], "archive_bytes": len(archive)}
    verify_baseline(manifest, source, resources)
    candidate = verify_archive(archive, manifest)[member]
    if decoder:
        decoder_proof = decoder_copy(home, grant, authorization_commit, candidate)
    else:
        candidate_notice(baseline, candidate)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as initial:
        for name, raw in members.items():
            initial.writestr("helper/" + name, raw, compress_type=zipfile.ZIP_DEFLATED)
    helper = buffer.getvalue()
    preparer, runner, support, button = prepare_trial(root, helper, grant["sequence"], decoder=decoder)
    signer = load(root / "publisher_signer.py", get_pinned(preparer.SIGNER, preparer.SIGNER_SHA))
    support.LAUNCHER_SHA = LAUNCHER
    support.DASHBOARD_SHA = grant["baseline_dashboard_sha256"]
    if decoder:
        support.SERVER_SHA = baseline_hash
        support.RUNTIME_SOURCES["server.py"] = baseline_hash
    public, signature = support.sign_ephemeral(signer.canonical(manifest), root)
    trial_signed = envelope(manifest, public, signature, signer.canonical)
    pin = sha(public)
    require(verify_manifest(trial_signed, pinned_key=pin) == manifest, "manager_sign_trial_signature_invalid")

    def trial_release(copied_dashboard, _branch):
        require(copied_dashboard == baseline, "manager_sign_trial_baseline_changed")
        return trial_signed, archive, candidate, pin

    support.signed_trial = trial_release
    proof = runner.run_trial(home, root / "remote", support, helper, None, None,
                             lambda port: button.request_update(port, runner, support))
    require(proof.get("copy_install") == "committed" and proof.get("copy_rollback") == "rolled_back"
            and proof.get("real_server_health") == "verified" and proof.get("macos_codesign") == "verified"
            and proof.get("synthetic_sqlite_and_config") == "preserved",
            "manager_sign_mac_trial_failed")

    # Never sign a task that expired or whose installed baseline changed
    # while the disposable install and rollback were running.
    require(time.time() < grant["expires_at"], "manager_sign_task_expired")
    get_pinned(CHANNEL, grant["stable_manifest_sha256"])
    verify_baseline(manifest, source, resources)
    public, signature = signer.sign(home / KEY, signer.canonical(manifest))
    signed = envelope(manifest, public, signature, signer.canonical)
    require(verify_manifest(signed, minimum_sequence=stable["sequence"]) == manifest,
            "manager_sign_publisher_signature_invalid")
    return {"state": "signed", "sequence": grant["sequence"], "archive_sha256": sha(archive),
            "manifest_sha256": sha(signed), "manifest_base64": base64.b64encode(signed).decode("ascii"),
            "copy_install": "committed", "copy_rollback": "rolled_back", "macos_codesign": "verified",
            **({"decoder": decoder_proof} if decoder else {})}


def run_sign_task(task, *, home=None, authorize_candidate=authorize, sign=sign_candidate):
    try:
        grant = parse_sign_task(task)
        archive = authorize_candidate(task, grant)
        home = Path.home().resolve() if home is None else Path(home)
        with tempfile.TemporaryDirectory(prefix="rapbrain-remote-sign-") as directory:
            if grant["schema"] == DECODER_GRANT:
                return sign(home, Path(directory).resolve(), grant, archive, task["authorization_commit"])
            return sign(home, Path(directory).resolve(), grant, archive)
    except (ValueError, RuntimeError, OSError, http.client.HTTPException, subprocess.SubprocessError) as error:
        reason = str(error)
        return {"state": "refused", "reason": reason if re.fullmatch(r"[a-zA-Z0-9_]{1,80}", reason)
                else type(error).__name__}
