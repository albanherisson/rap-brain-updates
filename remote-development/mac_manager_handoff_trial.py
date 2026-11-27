#!/usr/bin/env python3
"""Drive the Beta 14 update button through a real handoff on disposable copies."""

from contextlib import closing
import functools
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import types
import urllib.request


HERE = Path(__file__).resolve()
RAW = "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
SUPPORT_URL = (RAW + "169b1f1f735dee92f083a617883bb1245e655f2b"
               "/remote-development/mac_manager_signed_copy_trial.py")
SUPPORT_SHA = "9edb62dfbe1ce5b9bd22e20d2c0627676d7e0c6619f9f02a9635a2c071663ba1"
LOCALE_URL = (RAW + "15638ef4c6c93f266c208e6ed9d20049b14d7a36"
              "/decoder-next/manager_locale_repair_candidate.py")
LOCALE_SHA = "a3e2771286abd02fadecb926ff17e2a42aff32f55785743076fa630fcff85945"
MANAGER_SHA = "bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5"
APP_PATH = Path("Downloads/RapBrainManager_App_Beta14/Rap Brain Manager Beta 14.app")
STATE_PATH = Path("Downloads/RapBrainManagerBackups/secure-update")
SOURCE_PATH = Path("Downloads/rap-brain")
LAUNCHER = Path("Contents/Resources/launch_manager.py")
DASHBOARD = Path("Contents/Resources/dashboard_beta14.html")
BASE_MANAGER = Path("candidate/Contents/Resources/manager.py")
TRACK = {"artist": "Rap Brain P0", "title": "Disposable signed handoff", "lyrics": "Synthetic lyrics"}

SWIFT = r'''
import AppKit
import Darwin
import WebKit

final class Driver: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    let web: WKWebView
    init(url: URL) {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1000, height: 700), configuration: config)
        super.init()
        web.configuration.userContentController.add(self, name: "p0")
        web.navigationDelegate = self
        web.uiDelegate = self
        web.load(URLRequest(url: url))
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.evaluateJavaScript(#"""
        (() => {
          const button = document.querySelector('button.action.purple[onclick="installManagerUpdate()"]');
          if (!button) return false;
          const original = window.fetch.bind(window);
          window.fetch = async (url, options) => {
            const response = await original(url, options);
            if (url === '/api/rapbrain/manager-update' && options?.method === 'POST') {
              const json = await response.clone().json();
              window.webkit.messageHandlers.p0.postMessage(response.status === 202 && json.state === 'queued');
            }
            return response;
          };
          button.click();
          return true;
        })()
        """#) { value, error in
            if error != nil || (value as? Bool) != true { exit(2) }
        }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        completionHandler(frame.isMainFrame && message.hasPrefix("Installer une mise à jour signée"))
    }
    func userContentController(_ userContentController: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, (message.body as? Bool) == true else { exit(2) }
        print("queued")
        exit(0)
    }
}
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let driver = Driver(url: URL(string: CommandLine.arguments[1])!)
DispatchQueue.main.asyncAfter(deadline: .now() + 20) { exit(3) }
withExtendedLifetime(driver) { app.run() }
'''


def require(condition, error):
    if not condition:
        raise ValueError(error)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_bytes(path, expected, limit=2_000_000):
    require(path.resolve() == path and path.is_file(), "unexpected_source_path")
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    require(len(data) <= limit and sha(data) == expected, "source_hash_changed_" + path.stem)
    return data


def fetch_pinned(url, expected, limit):
    with urllib.request.urlopen(url, timeout=20) as response:
        data = response.read(limit + 1)
        require(response.geturl() == url and len(data) <= limit
                and sha(data) == expected, "trial_dependency_changed")
    return data


def load_support(root):
    path = root / "trial_support.py"
    source = checked_bytes(path, SUPPORT_SHA)
    support = types.ModuleType("p0_trial_support")
    exec(compile(source, str(path), "exec"), support.__dict__)
    return support


def activate(control):
    branch = control.parent
    home = branch / "home"
    state = home / STATE_PATH
    helper = state / "helper"
    require(Path.home().resolve() == home and control == branch / "control.json",
            "handoff_home_not_isolated")
    settings = json.loads(control.read_bytes())
    port, pin = settings["port"], settings["pin"]
    require(type(port) is int and 1024 <= port <= 65535 and port not in (8765, 11434)
            and re.fullmatch(r"[0-9a-f]{64}", pin), "handoff_control_invalid")
    expected = settings["helper_hashes"]
    require({path.name for path in helper.iterdir()} == set(expected),
            "handoff_helper_inventory_changed")
    for name, digest in expected.items():
        checked_bytes(helper / name, digest)
    sys.path.insert(0, str(helper))
    return home, state, settings


def copy_inspector(home, port):
    from creative_release import Refused
    from pending_attempt_recovery import require_no_local_listener

    def inspect(source, resources):
        require(source == home / SOURCE_PATH and resources == (home / APP_PATH / LAUNCHER).parent,
                "handoff_inspection_escaped")
        try:
            require_no_local_listener(port)
            listening = False
        except Refused as error:
            if str(error) != "local_listener_still_present_or_unknown":
                raise
            listening = True
        return {"server_process_seen": False, "manager_process_seen": False,
                "port_8765_listening": listening}
    return inspect


def stop_retained(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=4)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=4)


def stop_pending_helper(branch):
    from creative_release import Refused
    from process_start_identity import read_start

    record = read_json(branch / "helper-process.json")
    if record is None:
        return
    pid = record["pid"]
    try:
        if os.getpgid(pid) == pid and read_start(pid) == record["start"]:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, Refused):
        pass


def manager_parent(control):
    home, state, settings = activate(control)
    support = load_support(control.parent.parent)
    import manager_update_parent as parent
    import manager_update_release as release
    from process_start_identity import read_start

    launcher = home / APP_PATH / LAUNCHER
    checked_bytes(launcher.parent / BASE_MANAGER, MANAGER_SHA)
    code = checked_bytes(launcher, support.LAUNCHER_SHA)
    port, pin = settings["port"], settings["pin"]
    manifest = (control.parent / "release.json").read_bytes()
    archive = (control.parent / "release.zip").read_bytes()
    original_verify = release.verify_manifest
    verify = functools.partial(original_verify, pinned_key=pin)
    spec = verify(manifest)
    release.verify_archive(archive, spec)

    def read_test_channel(url, limit):
        values = {release.CHANNEL: manifest, spec["archive_url"]: archive}
        require(url in values and len(values[url]) <= limit, "handoff_channel_mismatch")
        return values[url]

    def spawn_helper(args, **options):
        require(Path(args[2]) == state / "helper/manager_update_helper.py", "handoff_helper_escaped")
        with (control.parent / "helper.log").open("xb") as log:
            child = subprocess.Popen([sys.executable, "-I", "-B", str(HERE),
                                      "--helper", str(control), *args[3:]],
                                     **(options | {"stdout": log, "stderr": subprocess.STDOUT}))
        try:
            (control.parent / "helper-process.json").write_text(
                json.dumps({"pid": child.pid, "start": read_start(child.pid)}))
        except BaseException:
            stop_retained(child)
            raise
        return child

    original_handoff = parent.prepare_handoff
    parent.prepare_handoff = functools.partial(
        original_handoff, port=port, launch_verifier=verify, spawner=spawn_helper,
        downloader=functools.partial(release.download_release, downloader=read_test_channel,
                                     pinned_key=pin))
    release.fetch, release.verify_manifest = read_test_channel, verify
    staged = types.ModuleType("manager_helper_release")

    def verify_staged(directory):
        require(directory == state, "handoff_staging_escaped")
        return state / "helper"
    staged.verify_staged = verify_staged
    sys.modules[staged.__name__] = staged

    namespace = {"__name__": "p0_manager_launcher", "__file__": str(launcher)}
    exec(compile(code, str(launcher), "exec"), namespace)
    # The copied launcher uses its real HTTP handler and handoff. Redirect
    # only its loopback references and test dependencies within this process.
    namespace["CHILD"] = namespace["CHILD"].replace("8765", str(port))
    request = namespace["request"]
    namespace["request"] = lambda target, *a, **kw: request(port if target == 8765 else target, *a, **kw)
    supervisor = {}
    original_launch = namespace["handle_launch_request"]

    def capture_launch(root, source, backup, state_ref):
        original_launch(root, source, backup, state_ref)
        supervisor.update(state_ref)
    namespace["handle_launch_request"] = capture_launch
    sys.argv = [str(launcher), "--no-browser"]
    try:
        return namespace["main"]()
    finally:
        stop_retained(supervisor.get("process"))


def external_helper(control, argv):
    home, state, settings = activate(control)
    support = load_support(control.parent.parent)
    import manager_update_helper as helper
    from mac_offline_bootstrap_gate import assert_offline
    from manager_offline_lifecycle import MacOfflineManagerLifecycle

    pin, port = settings["pin"], settings["port"]
    inspect = copy_inspector(home, port)
    observations = []
    active = None

    class CopyLifecycle(MacOfflineManagerLifecycle):
        def start_and_check(self):
            code_state = self._code_state()
            healthy = super().start_and_check()
            if healthy:
                status, runtime = support.local_json(port, "GET", "/api/status")
                # During maintenance, the signed runtime admits status and
                # authenticated proof while its ordinary health route is gated.
                healthy = (status == 200 and runtime.get("db") == str(self.source / "data/rapbrain.sqlite3")
                           and support.local_json(port, "GET", "/api/health")
                           == (503, {"error": "update_in_progress"}))
            observations.append([code_state, healthy])
            return healthy and not (settings["scenario"] == "rolled_back" and code_state == "candidate")

    def lifecycle(*args, **kwargs):
        nonlocal active
        active = CopyLifecycle(*args, **kwargs, pinned_key=pin, port=port, inspector=inspect)
        return active

    helper.verify_manifest = functools.partial(helper.verify_manifest, pinned_key=pin)
    helper.run_handoff = functools.partial(
        helper.run_handoff, lifecycle_factory=lifecycle,
        transaction_factory=functools.partial(helper.ManagerUpdateTransaction, pinned_key=pin),
        offline=functools.partial(assert_offline, inspector=inspect))
    try:
        result = helper.main(argv)
        (state / "trial-health.json").write_text(json.dumps(observations))
        return result
    except Exception as error:
        detail = str(error)
        (state / "trial-error.json").write_text(json.dumps(
            detail if re.fullmatch(r"[a-z0-9_]+", detail) else type(error).__name__))
        raise
    finally:
        if active is not None and active.owned is not None:
            stop_retained(active.owned.current)


def get_dashboard(port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        require(response.status == 200, "handoff_dashboard_unavailable")
        return response.read(256_000)
    finally:
        connection.close()


def wait_for(check, reason, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value is not None:
            return value
        time.sleep(0.15)
    raise ValueError(reason)


def read_json(path):
    try:
        return json.loads(path.read_bytes())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def choose_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    require(port not in (8765, 11434), "handoff_port_not_isolated")
    return port


def click_in_webkit(root):
    source, tool = root / "click.swift", root / "click-update"
    source.write_text(SWIFT)
    compiled = subprocess.run(["/usr/bin/xcrun", "swiftc", str(source), "-o", str(tool)],
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
    require(compiled.returncode == 0, "handoff_webkit_compile_failed")

    def click(port):
        result = subprocess.run([str(tool), f"http://127.0.0.1:{port}/"], capture_output=True,
                                stdin=subprocess.DEVNULL, timeout=24)
        require(result.returncode == 0 and result.stdout.strip() == b"queued",
                "handoff_update_button_failed")
    return click


def stage_reviewed_helper(support, helper_zip, backup, locale, directory):
    support.stage_helper(helper_zip, backup, directory)
    identity = directory / "process_start_identity.py"
    identity.write_bytes(locale["identity"](identity.read_bytes()))


def stage_scenario(branch, installed_app, installed_source, inventory, support, helper_zip,
                   backup, locale, scenario):
    from app_bundle_backup import _copy_verified
    from creative_transaction import safe_path

    home = branch / "home"
    app, source, state = home / APP_PATH, home / SOURCE_PATH, home / STATE_PATH
    app.parent.mkdir(parents=True, mode=0o700)
    source.mkdir(mode=0o700)
    state.mkdir(parents=True, mode=0o700)
    _copy_verified(installed_app, app, inventory)
    support.run_checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                        "handoff_copy_signature_invalid")
    checked_bytes(app / LAUNCHER, support.LAUNCHER_SHA)
    checked_bytes(app / LAUNCHER.parent / BASE_MANAGER, MANAGER_SHA)
    for name, expected in support.RUNTIME_SOURCES.items():
        (source / name).write_bytes(checked_bytes(safe_path(installed_source / name), expected))
    data = source / "data"
    data.mkdir(mode=0o700)
    (data / "ollama_model.json").write_text('{"model":"p0-fixture"}\n')
    helper = state / "helper"
    stage_reviewed_helper(support, helper_zip, backup, locale, helper)
    for module in helper.iterdir():
        module.chmod(0o600)
    signed, archive, payload, pin = support.signed_trial((app / DASHBOARD).read_bytes(), branch)
    (branch / "release.json").write_bytes(signed)
    (branch / "release.zip").write_bytes(archive)
    port = choose_port()
    control = branch / "control.json"
    control.write_text(json.dumps({"port": port, "pin": pin, "scenario": scenario,
                                   "helper_hashes": {p.name: sha(p.read_bytes()) for p in helper.iterdir()}}))
    return home, app, source, state, control, port, payload


def run_scenario(branch, installed_app, installed_source, app_inventory, support, helper_zip,
                 backup, locale, scenario, click):
    from app_bundle_backup import inventory
    from authenticated_runtime_client import assert_owned_listener
    from pending_attempt_recovery import require_no_local_listener

    home, app, source, state, control, port, payload = stage_scenario(
        branch, installed_app, installed_source, app_inventory, support, helper_zip,
        backup, locale, scenario)
    tmp = branch / "tmp"
    tmp.mkdir(mode=0o700)
    env = {"HOME": str(home), "TMPDIR": str(tmp), "PATH": "/usr/bin:/bin", "LANG": "C",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
           "RAP_BRAIN_PORT": str(port), "RAP_BRAIN_DATA": str(source / "data"),
           "OLLAMA_URL": "http://127.0.0.1:1", "RAP_BRAIN_MANAGER_NO_BROWSER": "1"}
    with (branch / "manager.log").open("xb") as log:
        manager = subprocess.Popen([sys.executable, "-I", "-B", str(HERE), "--manager", str(control)],
                                   env=env, cwd=branch, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        helper_completed = False
        try:
            def manager_ready():
                require(manager.poll() is None, "handoff_manager_exited_early")
                ports = list(tmp.glob("rapbrain-manager-beta-*/port.json"))
                return read_json(ports[0]) if len(ports) == 1 else None

            metadata = wait_for(manager_ready, "handoff_dashboard_timeout")
            manager_port = metadata["port"]
            require(manager_port not in (port, 8765, 11434), "handoff_dashboard_port_invalid")
            assert_owned_listener(manager_port, metadata["pid"])
            dashboard = get_dashboard(manager_port)
            match = re.search(rb"LAUNCH_TOKEN='([A-Za-z0-9_-]{30,80})'", dashboard)
            require(match is not None, "handoff_launch_token_missing")
            status, launch = support.local_json(manager_port, "POST", "/api/rapbrain/start",
                                                headers={"X-RB-Launch-Token": match[1].decode("ascii")})
            require(status == 200 and launch.get("queued") is True, "handoff_launch_not_queued")

            def server_ready():
                status, launch = support.local_json(manager_port, "GET", "/api/rapbrain/launch-state")
                require(status == 200 and launch.get("state") != "refused", "handoff_launch_refused")
                if launch.get("state") != "spawned":
                    return None
                try:
                    health = support.local_json(port, "GET", "/api/health")
                except (OSError, http.client.HTTPException):
                    return None
                return launch["pid"] if health == (200, {"ok": True, "worker": "separate_process"}) else None

            pid = wait_for(server_ready, "handoff_initial_health_timeout")
            assert_owned_listener(port, pid)
            status, track = support.local_json(port, "POST", "/api/tracks", body=json.dumps(TRACK),
                                              headers={"Content-Type": "application/json"})
            require(status in (200, 201) and type(track.get("id")) is int, "handoff_seed_track_failed")
            # Give the separately spawned worker time to acquire its idle lock.
            wait_for(lambda: True if (source / "data/decode-worker.lock").is_file() else None,
                     "handoff_initial_worker_missing")
            require(support.local_json(manager_port, "POST", "/api/rapbrain/manager-update")
                    == (403, {"error": "unauthorized"}), "handoff_button_token_not_required")
            assert_owned_listener(manager_port, metadata["pid"])
            click(manager_port)
            print("Bouton accepté : " + scenario, flush=True)
            def handoff_started():
                if manager.poll() is not None:
                    return manager.returncode
                snapshots = list(tmp.glob("rapbrain-manager-beta-*/manager-update-result.json"))
                result = read_json(snapshots[0]) if len(snapshots) == 1 else None
                if result and result.get("state") == "refused":
                    detail = result.get("detail", "")
                    raise ValueError(detail if re.fullmatch(r"[a-z0-9_]+", detail) else "handoff_parent_refused")
                return None
            require(wait_for(handoff_started, "handoff_manager_exit_timeout", timeout=45) == 42,
                    "handoff_manager_exit_code")
            def helper_finished():
                error = read_json(state / "trial-error.json")
                if error:
                    raise ValueError(error)
                return read_json(state / "trial-health.json")
            observations = wait_for(helper_finished, "handoff_helper_timeout", timeout=90)
            helper_completed = True
        finally:
            stop_retained(manager)
            if not helper_completed:
                stop_pending_helper(branch)

    receipt = read_json(state / "manager-handoff-result.json")
    require(receipt is not None and receipt.get("state") == scenario, "handoff_receipt_mismatch")
    expected = [["candidate", True]] if scenario == "committed" else [["candidate", True], ["baseline", True]]
    require(observations == expected, "handoff_real_health_not_proven")
    require_no_local_listener(port)
    require(not (state / "maintenance.ticket").exists(), "handoff_ticket_left")
    with closing(sqlite3.connect((source / "data/rapbrain.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        require(db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
                and db.execute("SELECT artist, title, lyrics FROM tracks").fetchall()
                == [(TRACK["artist"], TRACK["title"], TRACK["lyrics"])], "handoff_data_changed")
    require((source / "data/ollama_model.json").read_text() == '{"model":"p0-fixture"}\n',
            "handoff_config_changed")
    if scenario == "committed":
        require((app / DASHBOARD).read_bytes() == payload, "handoff_candidate_missing")
    else:
        require(inventory(app) == app_inventory, "handoff_rollback_bytes_changed")
    support.run_checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                        "handoff_final_signature_invalid")


def run_trial(home, root, support, helper_zip, backup, locale, click):
    helper_root = root / "dependencies"
    stage_reviewed_helper(support, helper_zip, backup, locale, helper_root)
    sys.path.insert(0, str(helper_root))
    from app_bundle_backup import inventory
    from creative_transaction import safe_path
    app = safe_path(home / APP_PATH, directory=True)
    source = safe_path(home / SOURCE_PATH, directory=True)
    before = inventory(app)
    for scenario in ("committed", "rolled_back"):
        print("Essai bouton Manager : " + scenario, flush=True)
        branch = root / scenario
        branch.mkdir(mode=0o700)
        run_scenario(branch, app, source, before, support, helper_zip, backup, locale, scenario, click)
    require(inventory(app) == before, "handoff_active_app_changed")
    for name, expected in support.RUNTIME_SOURCES.items():
        checked_bytes(source / name, expected)
    return {"status": "pass", "manager_button": "verified", "external_handoff": "verified",
            "copy_install": "committed", "copy_rollback": "rolled_back",
            "real_server_health": "verified", "health_refusal": "injected_after_real_probe",
            "macos_codesign": "verified", "synthetic_sqlite_and_config": "preserved",
            "active_sources_unchanged": True, "production_key_used": False}


def main():
    require(sys.platform == "darwin", "macos_required")
    if len(sys.argv) >= 3 and sys.argv[1] in ("--manager", "--helper"):
        def interrupted(_signum, _frame):
            raise SystemExit(2)
        signal.signal(signal.SIGTERM, interrupted)
        control = Path(sys.argv[2]).resolve()
        return manager_parent(control) if sys.argv[1] == "--manager" else external_helper(control, sys.argv[3:])
    require(len(sys.argv) == 1, "invalid_handoff_option")
    with tempfile.TemporaryDirectory(prefix="rapbrain-manager-handoff-") as temporary:
        root = Path(temporary).resolve()
        (root / "trial_support.py").write_bytes(fetch_pinned(SUPPORT_URL, SUPPORT_SHA, 50_000))
        support = load_support(root)
        helper_zip = support.fetch_helper()
        backup = support.fetch_bytes(support.BACKUP_URL, 20_000)
        locale = {}
        exec(compile(fetch_pinned(LOCALE_URL, LOCALE_SHA, 20_000), "locale_candidate.py", "exec"), locale)
        result = run_trial(Path.home().resolve(), root, support, helper_zip, backup, locale,
                           click_in_webkit(root))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, http.client.HTTPException,
            sqlite3.Error, subprocess.SubprocessError) as error:
        detail = str(error)
        print(json.dumps({"status": "failed", "reason": detail if re.fullmatch(
            r"[a-zA-Z0-9_]+", detail) else type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)
