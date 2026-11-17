"""Inspect and gracefully close only the reviewed Rap Brain Manager application."""

import json
from pathlib import Path
import subprocess
import tempfile
import time

from mac_manager_install_request import APP, LAUNCHER, compatible_launcher, open_manager
from manager_remote_request import decode_remote_json


SWIFT = r'''import AppKit
import CoreGraphics
import Foundation

struct Request: Decodable {
    let app: String
    let operation: String
}

func output(_ state: String, _ running: Bool, _ window: Bool) -> Never {
    let record: [String: Any] = ["state": state, "was_running": running, "window_present": window]
    let data = try! JSONSerialization.data(withJSONObject: record, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    exit(0)
}

func fail(_ reason: String) -> Never {
    FileHandle.standardError.write(Data(reason.utf8))
    exit(2)
}

let input = FileHandle.standardInput.readDataToEndOfFile()
guard input.count <= 4096,
      let request = try? JSONDecoder().decode(Request.self, from: input),
      ["snapshot", "close"].contains(request.operation) else {
    fail("remote_manager_native_request_invalid")
}
let appURL = URL(fileURLWithPath: request.app, isDirectory: true).standardizedFileURL
guard appURL.resolvingSymlinksInPath() == appURL,
      FileManager.default.fileExists(atPath: appURL.path) else {
    fail("remote_manager_native_app_missing")
}

func applications() -> [NSRunningApplication] {
    return NSWorkspace.shared.runningApplications.filter { app in
        guard let bundleURL = app.bundleURL,
              let executable = app.executableURL else { return false }
        return bundleURL.standardizedFileURL.resolvingSymlinksInPath() == appURL
            && executable.standardizedFileURL.resolvingSymlinksInPath().path.hasPrefix(appURL.path + "/Contents/MacOS/")
            && !app.isTerminated
    }
}

func windowExists(_ app: NSRunningApplication) -> Bool {
    guard let windows = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements],
                                                  kCGNullWindowID) as? [[String: Any]] else {
        return false
    }
    return windows.contains { window in
        guard let pid = window[kCGWindowOwnerPID as String] as? NSNumber,
              let layer = window[kCGWindowLayer as String] as? NSNumber,
              let bounds = window[kCGWindowBounds as String] as? [String: Any],
              let width = bounds["Width"] as? NSNumber,
              let height = bounds["Height"] as? NSNumber else { return false }
        return pid.int32Value == app.processIdentifier && layer.intValue == 0
            && width.doubleValue >= 160 && height.doubleValue >= 100
    }
}

let found = applications()
guard found.count <= 1 else { fail("remote_manager_native_multiple_instances") }
guard let app = found.first else { output("already_closed", false, false) }
let shown = windowExists(app)
if request.operation == "snapshot" {
    output("running", true, shown)
}
guard app.terminate() else { fail("remote_manager_native_quit_refused") }
let deadline = Date().addingTimeInterval(20)
while Date() < deadline {
    RunLoop.current.run(until: Date().addingTimeInterval(0.1))
    if app.isTerminated && applications().isEmpty {
        output("closed", true, false)
    }
}
fail("remote_manager_native_exit_unverified")
'''


def native_request(home, operation, *, call=subprocess.run):
    app = home / APP
    if app.resolve() != app or not compatible_launcher(app / LAUNCHER):
        raise ValueError("remote_manager_native_launcher_changed")
    if operation not in ("snapshot", "close"):
        raise ValueError("remote_manager_native_request_invalid")
    signature = call(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                     capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    if signature.returncode:
        raise ValueError("remote_manager_codesign_refused")
    with tempfile.TemporaryDirectory(prefix="rapbrain-manager-window-") as folder:
        source = Path(folder) / "manager_window.swift"
        source.write_text(SWIFT, encoding="utf-8")
        result = call(["/usr/bin/swift", str(source)],
                      input=json.dumps({"app": str(app), "operation": operation}).encode(),
                      capture_output=True, timeout=65)
    if result.returncode:
        reason = result.stderr.decode("utf-8", errors="replace").strip()
        if reason.startswith("remote_manager_native_") and len(reason) <= 80 and reason.replace("_", "").isalnum():
            raise ValueError(reason)
        raise ValueError("remote_manager_native_probe_failed")
    record = decode_remote_json(result.stdout)
    if (type(record) is not dict or record.keys() != {"state", "was_running", "window_present"}
            or type(record["was_running"]) is not bool or type(record["window_present"]) is not bool
            or record["state"] not in ("closed", "already_closed", "running")):
        raise ValueError("remote_manager_native_reply_invalid")
    if operation == "close" and record["state"] not in ("closed", "already_closed"):
        raise ValueError("remote_manager_native_exit_unverified")
    return record


def open_native_window(home, *, opener=open_manager, inspect=native_request,
                       clock=time.monotonic, sleep=time.sleep):
    opener(home / APP)
    deadline = clock() + 20
    while clock() < deadline:
        report = inspect(home, "snapshot")
        if report == {"state": "running", "was_running": True, "window_present": True}:
            return report
        sleep(0.5)
    raise ValueError("remote_manager_native_window_unverified")
