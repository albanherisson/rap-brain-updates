# Secure Creative Engine update — implementation pending lifecycle integration

Beta 14's owner-side validation passed on 27 October 2026: native launch,
SQLite/config backup, separate restoration and P8 signed staging/rollback.
This establishes the existing Manager as the baseline. It does not authorize
the P8 rehearsal package for production installation.

## Implemented here

- `creative_release.py` reuses the repository's strict signed JSON parser and
  the fingerprint pinned in Beta 14/P10. It downloads only from this repository's
  `creative-stable` GitHub Pages directory, refuses redirects, bounds downloads,
  verifies Ed25519 before downloading payload, and checks ZIP contents/digests.
- The production schema requires explicit authorization, fresh timestamps,
  increasing sequence, exact original engine/server hashes, no data migrations,
  and publisher-attested real Ollama/full-server validation. Those signed claims
  are release gates, not a substitute for actually running those validations.
- `creative_transaction.py` requires a lifecycle adapter. Without one it refuses
  before creating state or writing source. With a test adapter it performs a
  fresh SQLite online backup, mandatory Ollama config backup, integrity and
  byte-identical restore drill, then a journaled atomic replacement of exactly
  `creative_engine.py`. It preserves file permissions, locks concurrent updates,
  fsyncs critical writes, and recovers a crash between replacement and journal
  advancement. Failed health restores original code; it never restores a stale
  database over current data. A failed original restart leaves the original code
  restored and the process stopped, with an explicit result.
- Tests include a real child-process exit immediately after replacement,
  corrupted backups, unexpected local changes, busy-server refusal, replay,
  signature tampering, ZIP validation, and data preservation.

Only SQLite and `data/ollama_model.json` are backed up. Other data files are
untouched, not claimed as backed up. This engine supports one code-file change
without migrations; future updates affecting other files need a new scope.

## Two distinct signing identities

The legacy Manager key published in `docs/publisher-public-key.txt` hashes to
`5c7bda9ccdb4ee197ad10f907211f3b33ed74f5986066dd832bb3013df7dba78`.
The Creative Engine P8/P10 fingerprint is
`ae32610121418b50adcc8726df567a22ed7b3af67f804ef9aaaa7a1a4efce504`.

Do not replace one with the other, silently trust a downloaded public key, or
upload a private key. Creative Engine releases retain the P10 trust identity.
Test fixtures generate ephemeral keys and explicitly inject their pins; these
keys are never accepted by the production default.

## Not implemented or shipped

- No real-server lifecycle adapter; no automatic stop/restart of the user's Mac.
- No UI installation button enabled; no new app archive or Beta version.
- No production manifest signed/published; P8 remains rehearsal-only.
- No real Ollama success inferred from P10: the last P9 result failed with zero
  bars, and P9b was refused.
- No automatic rollback has been exercised against the live installation.
- Tests use disposable SQLite files and a fake lifecycle. macOS CI is separate
  evidence from the local Python run and from validation on the owner's Mac.

The maintenance context contract is security-critical: it must block new jobs
and launches, identify the owned server, refuse active analyses, confirm every
writer has stopped, and retain exclusion through commit/rollback. Checking an
HTTP port or `jobs` once does not meet this contract. Normal server startup must
also refuse pending transactions until recovery. The adapter must unwind its
maintenance state if transaction setup fails before the durable journal exists.
Both successful and rollback startup must be compatible with the unchanged
database schema; automatic rollback does not reverse application-side writes.

## Server structure received from the owner (27 October 2026)

The exact Beta 14 application archive is available separately in the project
files (483,156 bytes). Its `launch_manager.py` hashes to
`362ad3e1e3878cc49b90f76e212211e328e514b97c5a49b52921c0b4669964ba`;
the bundled candidate `manager.py` hashes to
`bdd2d65c9dce03fc11e0148879a5ed176ac96367aa7bce2e2874f6c72364d0d5`.
The launcher and dashboard compile/parse locally. This is source evidence,
not proof that the identical bytes remain on the owner's Mac.

The Beta 14 launch controller retains the exact `subprocess.Popen` handle for
a server it starts, but explicitly leaves automatic stopping disabled. It
checks port 8765 before launch, spawns `server.py` in a separate session,
and later polls that handle. It does not identify or stop a pre-existing
server, worker, or audio capture process. Its real installation buttons are
disabled; the signed Creative Engine action invokes the P10 copy rehearsal.
The disposable Manager HTTP child is terminated when Beta 14 closes, while
the launched Rap Brain server is deliberately left running. The future
production adapter can reuse the retained handle only for a server launched
by this Manager instance; other cases must refuse until ownership is proved.
The original Beta 14 archive passed its bundled `--smoke-test` in a disposable
Linux directory with a nonexistent Rap Brain source and separate test backup
path. It reported real stopping disabled and production POST operations blocked.
This does not substitute for macOS or live-server tests.

`beta14_launch_gate.py` now prepares only a separate copy of the exact pinned
Beta 14 `launch_manager.py`. It inserts a fail-closed read-only check inside
the existing ordinary-launch request handler. A private maintenance marker,
pending or malformed journal, or unsafe update-state path produces the normal
Beta 14 refusal report before `Popen`. A terminal journal permits an ordinary
launch only after the marker is gone. The patched disposable Beta 14 copy
passes its bundled smoke test; a direct request through its real handler with
a maintenance marker returns `update_recovery_required` and `launched: false`.
This does not alter the Mac app or authorize installation. The server lifetime
guard must still protect against launches outside this Manager, and the real
adapter must recover before clearing a marker.

A separately saved `server.py` in the project has SHA-256
`14c9cc00e6794a4d9709750f93a9d600cb525ad35973b85b88f8ada57a967b51`;
the archived `rap-brain.zip` server has
`8dbea5e4a2f0d4ec696fe0cb4719105db195a27e678e5fe6bf0b0a3dd79d31e6`.
Neither matches the live-server source hash below. They are historical copies,
not a basis for producing a production patch.

The redacted AST output matches the earlier `server.py` SHA-256
`4380ab4fd97d727ced4521eb66b11004e21f9f15c0eafaee955f1f0145913ad7`.
It confirms that `__main__` calls `init()`, starts `supervise_worker` and serves
HTTP. `supervise_worker` launches a second Python process running `worker_main`;
that process takes a file lock, calls `resume_jobs()` and loops over queued
jobs. The HTTP process's `finally` block requests worker termination and may
kill it after a timeout. An audio capture process is tracked separately by
`AUDIO_STATE`. `/api/status` reports Ollama/model availability, and `/api/jobs`
returns database rows; neither authenticates the server process or establishes
that the worker and audio process are idle.

Therefore the current Manager's HTTP port probe, a single jobs-list read, or
termination of an arbitrary PID cannot justify an update. The next integration
must establish a durable maintenance gate before job admission and before
`resume_jobs()`, quiesce both supervisor and worker without interrupting an
analysis, account for audio capture, and bind the process identity and health
check to the Manager-owned launch. An external controller must recover a pending
transaction before any normal server launch. The redacted AST hides literals,
including SQL and endpoint names, so these requirements are confirmed but the
precise gate implementation cannot be safely derived from this export alone.

The compact worker contract with the same server SHA-256 confirms that
`worker_main` selects the first queued job, `resume_jobs()` rewrites a prior
state on startup, and `job_runner` uses `running`, `done`, and `error`. The HTTP
API can also set `queued`, `pending`, `retry`, `interrupted`, and `cancelled`.
`creative_readiness.py` therefore reads only grouped job-status counts and
rejects every nonterminal or unknown status, before backup and again before
replacement. This conservative check does not substitute for an actual server
maintenance gate or verified worker/audio process identity.

An executable integration fixture now connects the transaction to the existing
owned-child supervisor. It starts a real dummy subprocess, stops that retained
handle, performs the signed transaction on a disposable source/data tree, and
checks both successful restart and failed-health rollback. The fixture refuses
any source without an exact disposable marker and fixed child script, and does
not accept a PID or attach to an existing Rap Brain process. This proves the
transaction/lifecycle interface works with a real subprocess; it does not prove
safe shutdown of the actual server and analysis worker.

`server_lifetime_guard.py` prepares an isolated copy of the exact pinned
server source with a shared, nonblocking OS lock held for each process lifetime.
The unchanged Manager's transaction lock is now distinct from this server
admission lock. The future lifecycle adapter must stop its verified, idle parent
and worker first, then take the server lock exclusively; a simultaneous new
server start loses the lock and aborts before calling `init()` or opening the
database. It must release that exclusive lock before starting its guarded
candidate, since the candidate needs a shared lock. The prepared guard now
checks a private durable `maintenance.ticket` after acquiring the shared
lock. The future adapter must create this marker while holding the exclusive
lock after verified shutdown, pass its ticket only to the owned candidate
(and its worker), and retain it until commit or rollback is terminal.
An unrelated launch without the ticket fails even during the restart handoff;
a crash leaves the marker in place and fails closed until recovery. This is
an accidental-launch exclusion mechanism, not authentication against code
running as the same macOS user. The high-level `prepare_admission()` also
wraps the server's HTTP GET and POST handlers with a separate short-lived
shared admission lock for the entire request. The future adapter must acquire
that lock exclusively to drain in-flight requests and create the marker
before releasing it; thereafter every POST and all GET routes except the
read-only `/api/status` receive HTTP 503. This includes the GET route that
may update the lexical index. The
redacted active-server structure accepts this exact AST insertion, but is
intentionally non-executable and is not a substitute for compiling and testing
the unredacted active source on the owner's Mac. Marker lifecycle, process
ownership, worker termination and audio capture still require the production
adapter.

`mac_bootstrap_readonly_probe.py` is the next single-action Mac check. It
reads only the exact active server source and the already extracted Beta 14
launcher, refuses changed fingerprints, fetches two fixed-commit public patch
preparers with pinned SHA-256, and compiles both guarded candidates in memory.
It prints only candidate digests and status. It neither saves a candidate nor
opens the database, config or private key, starts a process, or installs code.
On 27 October 2026 the owner ran this corrected probe on the Mac. It
recognized both active baselines and compiled the candidates in memory:

- guarded server SHA-256:
  `637cee464343207a7423917de5fa00e4e3cdf0338f5e6d58d9a7dcafdf4f646c`;
- guarded Beta 14 launcher SHA-256:
  `30354aa6838d8dad6348eef9f607d178f582b94e7342f429abf0db4a603b7aa7`.

The probe reported no active files modified, database opened or server started.
This establishes source compatibility, not runtime safety, installation or
release authorization. The earlier probe refused
`unexpected_entrypoint_format` before any candidate was created; its
AST-equivalent spelling check was corrected and the new run passed.

Executable fixtures verify the lock conflict and the ticketed restart with
real Python processes, including refusal without a ticket or with a corrupt
marker. A separate signed transaction fixture exercises the handoff while
backing up disposable SQLite/config data and replacing the engine on a copy.
This is only source preparation on copies: there is
no patched `server.py` installed on the owner's Mac, no signed bootstrap release,
and no production lifecycle adapter yet. A first bootstrap must be designed and
signed separately before this guard can protect subsequent updates.

Crash drills also terminate the updater subprocess after a durable verified
backup, immediately before replacement, and immediately after replacement
but before the journal advances. Recovery aborts the first without changing
the engine and restores the original code in the latter two cases. These are
disposable fixture drills; they have not been run against the live app.

## Next evidence needed

The earlier source review deliberately omitted `server.py` because it might
contain credentials. Do not request the unredacted file or upload the data folder.
`mac_server_structure.py` reads only this Python source, removes comments and
literal values (apart from a tiny fixed lifecycle vocabulary), and copies an
AST rendering to the macOS clipboard. It does not import or execute the server,
open SQLite, write reports, or modify the installation. The output is structural
review material and is intentionally not runnable replacement code.

Source compatibility is now confirmed on the owner's Mac. The remaining
evidence is runtime identity and quiescence: the Manager must know whether it
owns the HTTP process, prove the analysis worker has exited without
interrupting a job, detect any active or orphaned audio capture, and keep the
HTTP admission marker through health and rollback. Integrate this with the
existing Beta 14 launcher/UI, validate it on disposable copies, resolve real
Ollama generation, and only then sign an eligible production release with the
existing Creative Engine publisher key on the owner's Mac.

`creative_shutdown_policy.py` now expresses the fail-closed shutdown
boundary without signaling a process. It requires the exact retained Manager
process handle, an authenticated parent/worker identity, verified worker and
audio idle states, a drained HTTP gate and durable marker, only terminal job
states, and a server process group containing exactly the parent and worker.
It also compares a fresh OS start token for the owned parent with the token
recorded at launch, and requires both parent and worker to execute the exact
pinned server source. The future collector must obtain these values from OS
process metadata immediately before signaling; a bare PID or copied Boolean
is insufficient.
Unknown or extra processes refuse shutdown. These are requirements for a
future evidence collector; no such authenticated runtime proof has been
collected on the owner's Mac, and this policy does not enable stopping it.

`worker_activity_gate.py` is a disposable process fixture primitive for the
remaining worker race. Its shared lock covers an entire job, while an updater
must first take the HTTP admission lock exclusively to drain requests, then
take the job lock exclusively before durably creating the maintenance marker.
The fixture shows that an active job refuses maintenance and that a subsequent
job cannot start while the marker remains. An in-flight HTTP request also
refuses maintenance before the marker exists. The marker is deliberately not
removed during a crash or a nonterminal phase. A separate explicit finalizer
requires a private terminal journal with the expected transaction ID, the
matching ticket, and a verified owned-process health result; malformed or
duplicate journal fields leave the marker intact. The future lifecycle owner
must supply these facts and call that finalizer after commit or rollback.
This module is not yet inserted into
the Mac server or connected to Beta 14, so no live worker exclusion is claimed.

`server_worker_activity_candidate.prepare_worker_activity()` now prepares an additional
isolated server candidate: it wraps `job_runner` with the same job lock and
marker check, and makes a newly started worker wait before `init()` and
`resume_jobs()` while maintenance is pending. Its AST shape compiles against
the owner's redacted server structure and its behavior passes a synthetic
server fixture. Since that redacted structure is intentionally non-executable,
this is still not validation of the unredacted candidate on the owner's Mac.
The existing prepared candidate and read-only Mac probe remain unchanged;
this new source variant is not installed or distributed.

`mac_worker_candidate_readonly_probe.py` provides one further owner-side
compatibility check for that variant. It reads the known live `server.py`,
verifies the original SHA-256, fetches only the two public preparers at a fixed
commit with independent SHA-256 pins, and compiles the new candidate entirely
in memory. It does not import/execute the server or read data, config or keys.
On 29 October 2026 the owner ran this check on the Mac. It recognized the
original active source and compiled the worker-gated candidate in memory with
SHA-256 `faea0a686f5cb008a906b680d5e3cbdcd4b9fef3b60eb1e9a0769ef2f4fca925`.
The output reported no active file modified, database opened or server started.
This establishes source compatibility only; it cannot prove the running worker
is idle or enable installation.

A further isolated `server_worker_resume_candidate.py` wraps `resume_jobs()`
with the same worker job lock. This closes a gap at worker startup: a resumed
analysis cannot rewrite job state while a maintenance marker is present.
It also provides a read-only runtime route protected by a 64-character launch
token provided by the Manager. The route reports only the parent, worker and
audio process IDs, and rejects an absent or wrong token. This is one input to
the future ownership check, not proof that a returned PID is safe to stop;
the retained launch handle and fresh OS process inventory still have to match.
The candidate now also reports whether the retained worker launch arguments
refer to this exact server script and Python executable; mismatches remain a
refusal condition. It does not return the full command line or any token.
`process_group_inventory.py` now parses a read-only OS process snapshot and
refuses a server whose parent is not the Manager, a worker whose parent is not
that server, or any third process in their group (including an orphaned audio
helper). A failed or malformed OS snapshot refuses the operation. This does
not yet bind a live Mac process to the launch handle or enable any signal.
`process_start_identity.py` checks a retained child handle before and after a
read-only OS start-time query and rejects a changed process identity. The
format parser rejects ambiguous or extra output. Both collectors must still
be integrated into the same authenticated, atomic maintenance flow; their
standalone success never authorizes a process stop.
`authenticated_runtime_client.py` now sends only a token-protected request to
`127.0.0.1`, bounds the JSON response, rejects duplicate/unknown fields,
requires the returned parent PID to equal the retained Manager child, and
refuses an active audio PID or mismatched worker script. A real loopback
fixture tests the valid and refused cases. This client remains read-only and
has no connection to a production stop or installer.
`beta14_runtime_token_candidate.py` prepares a separate copy of the exact
Beta 14 launcher. It reuses the pinned ordinary-launch gate, gives a fresh
256-bit random probe token only to the `Popen` child through its environment,
and retains it next to the owned process handle in private supervisor state.
The token is never included in the launch report. The exact owner archive
compiles in a disposable local copy; a synthetic spawn test verifies token
handoff without starting Rap Brain. No installed or signed Manager release
exists for this candidate.
Synthetic behavior tests and the redacted AST compilation pass. The earlier
Mac result applies to the previous byte-identical candidate only; this newer
variant needs its own read-only Mac compatibility check after the remaining
lifecycle pieces are ready. Neither variant has been installed.

Run tests: `python -m unittest discover -s manager-updater -p 'test_*.py' -v`.
