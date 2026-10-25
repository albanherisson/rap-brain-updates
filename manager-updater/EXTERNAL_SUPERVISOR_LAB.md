# External supervisor prototype — NOT AN INSTALLER

Prepared 25 October 2026. Its reference test suite has **12/12 passing tests** run in a local isolated Python environment, including a separate subprocess, unexpected termination before/after replacement, recovery on the next invocation, invalid transaction state, symlink refusal, malicious backup refusal, and healthy commit/rollback.

The repository module `disposable_supervisor_lab.py` is a **reduced, fixture-only demonstration**. It permits operations exclusively inside a directory literally named `DisposableSupervisorFixture` containing the marker `RAPBRAIN_DISPOSABLE_SUPERVISOR_FIXTURE_V1`, and cannot update `Rap Brain Manager.app`. The separate local reference suite is not included in this repository module and should not be mistaken for production CI.

**Critical gaps**: durability for unexpected power loss, persisted cross-process lock, launchd integration, macOS process ownership and PID reuse, trustworthy health check, minimum privileges, a real publisher-signed release, testing with the actual app bundle, and backup preservation of a custom app icon.

No installed app, private signing key or Rap Brain data was touched in these tests.