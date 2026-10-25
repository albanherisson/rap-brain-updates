# Mac process-identity gate — safety-only prototype

The read-only process gate distinguishes the already-observed Manager PID/port from unrelated Python servers and rejects unexpected state fields and misleading command substrings. **16/16 automated local tests pass.** This prototype has no process stop, signal, launch, or install functions.

The real Manager was observed responding to HTTP at PID 48297 and local TCP port 62788 on 25 October 2026. These are ephemeral observations, **not hardcoded targets** for future installation.

**Production safety requirements still open:**
- PID reuse protection by checking OS process start time and current executable identity immediately before any signal;
- an authenticated process health endpoint or verifiable server ownership (HTTP 200 on a local port alone is not proof of ownership);
- robust handling of interpreter path quoting and unknown argv forms (fail closed);
- cooperative shutdown, external process supervisor, locking, durable atomic replacement, health-verified restart, safe automatic rollback;
- validation on a copy of the actual Mac application and preservation of its icon and Rap Brain data.

The existing Mac launcher and Manager remain unchanged; do not use this prototype to kill any process.
