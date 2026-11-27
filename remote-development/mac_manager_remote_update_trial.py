#!/usr/bin/env python3
"""Exercise the Manager update request without a browser click, on copies only."""

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request


RUNNER_URL = ("https://raw.githubusercontent.com/albanherisson/rap-brain-updates/"
              "cdb675c3b28ae30f619833fd71490564b630fae2/"
              "remote-development/mac_manager_handoff_trial.py")
RUNNER_SHA = "c68d0c9d85a4f82e9d9caf9ef4970fe40bed84098f9b3005d591b62d9bc6b783"
DASHBOARD_14_SHA = "cd698665767d379c312ada30cdcbebf0157fba6bda1f3aa501bb982d41872259"
UPDATE_TOKEN = re.compile(rb"\bSIGNATURE_TOKEN='([A-Za-z0-9_-]{30,80})'")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def get_runner(root):
    with urllib.request.urlopen(RUNNER_URL, timeout=20) as response:
        raw = response.read(50_001)
        require(response.geturl() == RUNNER_URL and len(raw) <= 50_000
                and hashlib.sha256(raw).hexdigest() == RUNNER_SHA, "remote_trial_runner_changed")
    path = root / "handoff_runner.py"
    path.write_bytes(raw)
    spec = importlib.util.spec_from_file_location("p0_handoff_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def request_update(port, runner, support):
    """Called only after the copy harness verified the dashboard listener."""
    require(type(port) is int and 1024 <= port <= 65535 and port not in (8765, 11434),
            "remote_trial_port_not_isolated")
    dashboard = runner.get_dashboard(port)
    tokens = UPDATE_TOKEN.findall(dashboard)
    require(len(tokens) == 1, "remote_trial_manager_token_unavailable")
    status, result = support.local_json(port, "POST", "/api/rapbrain/manager-update",
                                       headers={"X-RB-Manager-Token": tokens[0].decode("ascii")})
    require(status == 202 and result == {"state": "queued"}, "remote_trial_request_refused")


def run_trial(home, root):
    runner = get_runner(root)
    (root / "trial_support.py").write_bytes(
        runner.fetch_pinned(runner.SUPPORT_URL, runner.SUPPORT_SHA, 50_000))
    support = runner.load_support(root)
    dashboard = home / runner.APP_PATH / runner.DASHBOARD
    require(dashboard.resolve() == dashboard and dashboard.is_file()
            and dashboard.stat().st_size <= 250_000, "remote_trial_dashboard_unavailable")
    digest = hashlib.sha256(dashboard.read_bytes()).hexdigest()
    require(digest in (support.DASHBOARD_SHA, DASHBOARD_14_SHA), "remote_trial_dashboard_changed")
    support.DASHBOARD_SHA = digest
    helper = support.fetch_helper()
    backup = support.fetch_bytes(support.BACKUP_URL, 20_000)
    locale = {}
    exec(compile(runner.fetch_pinned(runner.LOCALE_URL, runner.LOCALE_SHA, 20_000),
                 "locale_candidate.py", "exec"), locale)
    result = runner.run_trial(home, root, support, helper, backup, locale,
                              lambda port: request_update(port, runner, support))
    # The same authenticated endpoint ran the transaction in both scenarios.
    # The previous harness uses the manager_button field for its driver.
    require(result.pop("manager_button") == "verified", "remote_trial_request_unverified")
    return result | {"manager_request": "programmatic_verified", "scope": "temporary_copies"}


def main():
    require(sys.platform == "darwin" and len(sys.argv) == 1, "remote_trial_macos_required")
    with tempfile.TemporaryDirectory(prefix="rapbrain-remote-update-") as temporary:
        result = run_trial(Path.home().resolve(), Path(temporary).resolve())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        reason = str(error)
        if not re.fullmatch(r"[a-zA-Z0-9_]+", reason):
            reason = type(error).__name__
        print(json.dumps({"status": "failed", "reason": reason}), file=sys.stderr)
        raise SystemExit(2)
