"""Inspect and gracefully close only the reviewed Rap Brain Manager application."""

import json
from pathlib import Path
import subprocess
import tempfile

from mac_manager_install_request import APP, LAUNCHER, compatible_launcher
from manager_remote_request import decode_remote_json


SWIFT = r'''import AppKit
import CoreGraphics
import Foundation
import Security

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
      ["snapshot", "close", "open"].contains(request.operation) else {
    fail("remote_manager_native_request_invalid")
}
let appURL = URL(fileURLWithPath: request.app, isDirectory: true).standardizedFileURL
guard appURL.resolvingSymlinksInPath().path == appURL.path,
      FileManager.default.fileExists(atPath: appURL.path) else {
    fail("remote_manager_native_app_missing")
}

func codeHash(_ code: SecStaticCode) -> Data? {
    var information: CFDictionary?
    guard SecCodeCopySigningInformation(code, SecCSFlags(rawValue: 0), &information) == errSecSuccess,
          let values = information as? [String: Any],
          let hash = values[kSecCodeInfoUnique as String] as? Data,
          hash.count >= 20 else { return nil }
    return hash
}

func validatedStaticCode(_ url: URL) -> SecStaticCode? {
    var code: SecStaticCode?
    guard SecStaticCodeCreateWithPath(url as CFURL, SecCSFlags(rawValue: 0), &code) == errSecSuccess,
          let code = code,
          SecStaticCodeCheckValidity(code, SecCSFlags(rawValue: kSecCSStrictValidate | kSecCSCheckNestedCode), nil) == errSecSuccess else {
        return nil
    }
    return code
}

guard let expectedCode = validatedStaticCode(appURL),
      let expectedHash = codeHash(expectedCode),
      let expectedIdentifier = Bundle(url: appURL)?.bundleIdentifier else {
    fail("remote_manager_native_expected_signature_unverified")
}

func identityFailure(_ app: NSRunningApplication) -> String? {
    if app.isTerminated { return "remote_manager_native_launch_exited" }
    guard app.bundleIdentifier == expectedIdentifier else {
        return "remote_manager_native_bundle_identifier_mismatch"
    }
    guard let bundleURL = app.bundleURL else { return "remote_manager_native_bundle_url_missing" }
    guard let executable = app.executableURL else { return "remote_manager_native_executable_url_missing" }
    let actual = bundleURL.standardizedFileURL.resolvingSymlinksInPath()
    guard executable.standardizedFileURL.resolvingSymlinksInPath().path.hasPrefix(actual.path + "/Contents/MacOS/") else {
        return "remote_manager_native_executable_outside_bundle"
    }
    // Gatekeeper may launch a copy at another URL. Validate its sealed code,
    // resources and loaded process against the exact reviewed app version.
    guard let staticCode = validatedStaticCode(actual), codeHash(staticCode) == expectedHash else {
        return "remote_manager_native_bundle_signature_mismatch"
    }
    var runningCode: SecCode?
    let attributes = [kSecGuestAttributePid as String: NSNumber(value: app.processIdentifier)] as CFDictionary
    guard SecCodeCopyGuestWithAttributes(nil, attributes, SecCSFlags(rawValue: 0), &runningCode) == errSecSuccess,
          let runningCode = runningCode,
          SecCodeCheckValidity(runningCode, SecCSFlags(rawValue: 0), nil) == errSecSuccess else {
        return "remote_manager_native_process_signature_unverified"
    }
    var loadedStaticCode: SecStaticCode?
    guard SecCodeCopyStaticCode(runningCode, SecCSFlags(rawValue: 0), &loadedStaticCode) == errSecSuccess,
          let loadedStaticCode = loadedStaticCode, codeHash(loadedStaticCode) == expectedHash else {
        return "remote_manager_native_process_signature_mismatch"
    }
    return nil
}

func belongsToManager(_ app: NSRunningApplication) -> Bool {
    // Filter unrelated apps before any signature inspection.
    return app.bundleIdentifier == expectedIdentifier && identityFailure(app) == nil
}

func applications() -> [NSRunningApplication] {
    return NSWorkspace.shared.runningApplications.filter(belongsToManager)
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
guard found.count <= 8 else { fail("remote_manager_native_too_many_instances") }
if request.operation == "open" {
    if let app = found.first(where: windowExists) {
        app.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
        output("running", true, true)
    }
    let configuration = NSWorkspace.OpenConfiguration()
    configuration.activates = true
    configuration.addsToRecentItems = false
    configuration.allowsRunningApplicationSubstitution = false
    configuration.createsNewApplicationInstance = found.isEmpty
    configuration.promptsUserIfNeeded = false
    NSWorkspace.shared.openApplication(at: appURL, configuration: configuration) { launched, error in
        DispatchQueue.main.async {
            if let error = error {
                let code = String((error as NSError).code).replacingOccurrences(of: "-", with: "n")
                fail("remote_manager_native_launch_error_" + code)
            }
            guard let app = launched else { fail("remote_manager_native_launch_result_missing") }
            let deadline = Date().addingTimeInterval(20)
            while Date() < deadline {
                if app.isTerminated { fail("remote_manager_native_launch_exited") }
                if let reason = identityFailure(app) { fail(reason) }
                let current = applications()
                guard current.count <= 8 else { fail("remote_manager_native_too_many_instances") }
                if current.contains(where: { $0.processIdentifier == app.processIdentifier }) && windowExists(app) {
                    output("running", true, true)
                }
                RunLoop.current.run(until: Date().addingTimeInterval(0.1))
            }
            fail("remote_manager_native_window_missing")
        }
    }
    let deadline = Date().addingTimeInterval(35)
    while Date() < deadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
    }
    fail("remote_manager_native_launch_timeout")
}
guard !found.isEmpty else { output("already_closed", false, false) }
let shown = found.contains(where: windowExists)
if request.operation == "snapshot" {
    output("running", true, shown)
}
for app in found {
    if let reason = identityFailure(app) { fail(reason) }
    guard app.terminate() else { fail("remote_manager_native_quit_refused") }
}
let deadline = Date().addingTimeInterval(20)
while Date() < deadline {
    RunLoop.current.run(until: Date().addingTimeInterval(0.1))
    if found.allSatisfy({ $0.isTerminated }) && applications().isEmpty {
        output("closed", true, false)
    }
}
fail("remote_manager_native_exit_unverified")
'''


def native_request(home, operation, *, call=subprocess.run):
    app = home / APP
    if app.resolve() != app or not compatible_launcher(app / LAUNCHER):
        raise ValueError("remote_manager_native_launcher_changed")
    if operation not in ("snapshot", "close", "open"):
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
                      capture_output=True, timeout=90)
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
    if operation == "open" and record != {"state": "running", "was_running": True, "window_present": True}:
        raise ValueError("remote_manager_native_window_unverified")
    return record


def open_native_window(home, *, inspect=native_request):
    return inspect(home, "open")
