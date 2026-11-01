# External supervisor process-identity policy (prototype)

This phase adds a **pure, side-effect-free** identity comparison module and 16 unit tests.
It does not inspect the user's Mac, send signals, install updates or stop processes.

The current observed PID 48297 and port 62788 are test fixtures only, never operational targets.
Comparisons require process start timestamp, UID, interpreter/script paths and SHA-256,
socket ownership and authenticated health. All absent/ambiguous evidence must be rejected.

**Important:** even matching snapshots cannot authorize `kill(pid)` due to the
time-of-check/time-of-use race. A production macOS implementation must use a
stable kernel-supported process identity or a cooperative authenticated shutdown
protocol under a dedicated external supervisor, verify it just before stop,
and prove exit of the same instance. It must not rely solely on `ps`,
`lsof` or HTTP 200.

Further blockers: implement Mac observation adapter, trusted authentication,
signed release verification, durable transaction journal and lock, installable
supervisor, tested crash recovery and isolated app-bundle validation. No
installed Rap Brain Manager or user library modifications are permitted.
