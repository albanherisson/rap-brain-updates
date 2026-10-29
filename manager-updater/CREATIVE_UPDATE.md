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
Before sending the private token it also requires the local listener PID to
match the retained child through a bounded macOS `lsof` query, and checks again
after the response. A different or uninspectable listener refuses the request.
This OS query has not yet been validated on the owner's Mac.
`beta14_runtime_token_candidate.py` prepares a separate copy of the exact
Beta 14 launcher. It reuses the pinned ordinary-launch gate, gives a fresh
256-bit random probe token only to the `Popen` child through its environment,
and retains it next to the owned process handle in private supervisor state.
The token is never included in the launch report. The exact owner archive
compiles in a disposable local copy; a synthetic spawn test verifies token
handoff without starting Rap Brain. No installed or signed Manager release
exists for this candidate.
`beta14_owned_identity_candidate.py` builds on that same isolated launcher
copy and records the exact `server.py` hash and OS start timestamp at the
moment its retained `Popen` child is created. A failed OS query leaves the
timestamp absent, which must disable a future updater while preserving the
ordinary launch. Synthetic spawn tests and compilation of the exact archived
Beta 14 source pass. The Mac app has not received this candidate.
`owned_supervisor_binding.py` now refuses to enter a future install without
the exact retained Popen handle, private launch token, OS start identity and
server source hash recorded by that candidate. It compares the hash to the
signed update's required server hash and rechecks the live handle. It is
read-only, has no PID signalling and is not wired to a live update request.

## Remaining transaction handoff blocker

The transaction enters `lifecycle.maintenance()` before writing its first
`transaction.json` phase. If a future adapter creates `maintenance.ticket`
there and the Manager crashes before the journal is durable, ordinary launch
correctly refuses, while `Transaction.recover()` currently sees no journal.
No code replacement has happened, but clearing the marker without proving the
unchanged baseline and the ownership of that exact maintenance attempt would
be unsafe. The production adapter must create a durable attempt identity
before the marker, then implement authenticated recovery of this pre-journal
window. This must be drilled with a killed updater process before enabling any
real stop or UI install button. The new runtime token and OS readers are still
independent safety components; they have not closed this handoff gap.
`mac_combined_readonly_probe.py` batches the next source compatibility check
into one owner action. It pins four public preparer hashes to a fixed commit,
reads only the original active server and Beta 14 launcher after checking
their known digests, and compiles the current guarded candidates in memory.
It prints only two candidate hashes. Passing it still cannot authorize a real
stop, bootstrap or installation; the durable pre-journal handoff remains open.
On 29 October 2026 the owner ran the combined check on the Mac. Both original
active sources matched, and the candidates compiled in memory:

- server SHA-256: `c579c60c2034185de403306464607f5d0c04ed9ba0fee35d37cf27a34bd58376`;
- Beta 14 launcher SHA-256: `b1c851c335b4270c0b708379f8b7a8b3e7b8c0c747380c06e99bc0c8be99ac35`.

The owner reported no active file modified, database opened or server started.
This is source compatibility only. Neither candidate has been installed.

`prejournal_intent.py` now supplies a disposable durable attempt record written
before the maintenance marker. Its pre-journal recovery checks that the engine
and server still match the recorded hashes, that the prior journal has not
advanced, and that the server lifetime lock is exclusively available. It then
checks the ticket under the HTTP and worker locks before removing the marker.
A killed-updater process drill recovers the unmodified fixture; altered code,
an advanced journal, or a running server leave the marker in place. The real
Beta 14 transaction has not yet been wired to this attempt record; until it
is, the pre-journal production blocker remains open.
The transaction can now accept the same validated 32-character ID from its
lifecycle lease instead of generating a second one. The explicit finalizer can
require a matching intent, terminal journal and ticket before removing both
the marker and intent under the HTTP and worker locks. Disposable tests cover
the matching handoff and a mismatched transaction. A production adapter still
has to provide the lease, authenticated health and process stop/restart; no
live installation is enabled.
An additional disposable integration test now drives the signed engine
transaction with a lifecycle fixture that creates the durable intent and
marker, uses the same ID in its real SQLite/config backup journal, and removes
both only after a committed healthy result. The fixture verifies the entire
data folder remains byte-identical. This is interface evidence, not the real
Manager-owned process adapter.

`runtime_evidence.py` now collects a single read-only shutdown boundary for a
retained Manager child. Under exclusive HTTP and worker locks it checks the
private ticket, launch script hash and retained handle start identity, obtains
the token-authenticated parent/worker/audio report, checks fresh OS parentage
and process group, reads only grouped SQLite job states, and rechecks the handle.
The launch argument check matches the exact Beta 14 supervisor command
`[sys.executable, '-u', server.py]`; an earlier two-argument assumption was
corrected before wiring any live stop.
It rejects a queued job or busy worker lock. It never signals a process, and
its success is only a short-lived snapshot: the future lifecycle adapter must
create/authenticate the maintenance attempt first and collect it again directly
before stopping the exact owned handle. The endpoint is supplied only by the
isolated guarded server candidate, not the live server. A separate signed
bootstrap and real Mac lifecycle validation are still required.

`server_graceful_shutdown_candidate.py` prepares a further isolated server
variant with a token- and ticket-protected stop request. It requires the
durable marker, an idle worker lock, the retained worker's expected launch
arguments, and no tracked audio capture before asking the HTTP server to exit
through `serve_forever().shutdown()`. The existing main `finally` then handles
its worker. A synthetic handler test checks refusal and the shutdown request;
it does not prove that the real parent and worker exit cleanly. No stop request
has been sent to the owner's Mac. An owned-handle client must recheck the OS
identity, send the request only to that process, wait for both exits, and hold
the maintenance marker through rollback before this can become an installer.

`owned_graceful_stop.py` now joins those pieces without PID signalling: it
collects fresh authenticated/OS/SQLite idle evidence, rechecks the loopback
listener owner, requests the token- and ticket-gated stop, waits for the exact
retained child handle, verifies its entire process group is gone, and acquires
the server lifetime lock exclusively. It returns that lock still held for the
ticketed restart handoff. A local loopback fixture checks the request, successful
exit and timeout refusal; no live Rap Brain process has been stopped. The
Manager lifecycle adapter must still own this lease, create the durable intent,
coordinate journal recovery and candidate health, and keep the ticket until a
terminal transaction. The real server's graceful exit and worker cleanup have
not been exercised on the owner's Mac.

The exact Beta 14 server launch includes Python's `-u` argument; the runtime
collector now requires those three exact launch arguments instead of the
incorrect two-argument shape used by its first fixture. A disposable integration
test now starts a real guarded HTTP parent and worker subprocess, creates the
maintenance marker, requests their graceful exit and verifies the SQLite/config
fixture bytes remain identical. The execution environment cannot run its own
`ps -p` inventory, so that test substitutes the independently tested OS
collectors; it does not claim the actual Mac process inventory passed.

`mac_shutdown_readonly_probe.py` prepares one later owner-side compatibility
check for the final graceful-stop server candidate. It pins the existing three
public preparer sources to a fixed commit, reads only the previously recognized
original `server.py`, checks for the local read-only listener inventory tool,
and compiles the candidate entirely in memory. It never opens the database or
executes/stops the server.
On 29 October 2026 the owner ran this check on the Mac. It recognized the
unchanged active source and compiled the complete candidate in memory with
SHA-256 `2771e29b46b25ce86439c6d9eb28497395a1ea280a741aa8bf648e741d2b49dd`.
The report confirms no active file changed, database opened or process stopped.
It does not validate the server's actual runtime exit or install the candidate.

A further disposable integration drill now connects a locally signed engine
transaction to a real guarded HTTP parent and analysis worker. It checks both
a healthy commit and failed-health rollback, using the same durable attempt ID,
mandatory SQLite/config backup and restore check, and byte-identical data-folder
snapshot. The real parent exits via the token/ticket stop endpoint; the fixture
restarts the old code after a failed candidate. OS process start and process
group collectors are substituted in this sandbox and remain unvalidated on the
owner's Mac. The release signer is ephemeral test-only, not the production key.
This drill is not a production Manager lifecycle adapter or an enabled UI button.
The transaction itself now refuses a new signed installation if either a
maintenance ticket or pre-journal intent remains, even when the last journal
looks terminal. This closes an unsafe path where an incomplete older attempt
could otherwise reach the next install through a permissive lifecycle fixture.
Explicit verified recovery is still required to clear such artifacts.

The final isolated server and launcher candidates now pass through
`recovery_start_guards.py`. A direct `server.py` start refuses an orphaned
pre-journal intent, a pending/malformed transaction journal, or a journal for
another source even if its ticket is missing. The ordinary Beta 14 launch
likewise refuses an orphaned intent. Ticketed transaction restarts still use
the existing guarded path. The older Mac read-only probes and their pinned
preparers remain unchanged; the owner's previous candidate hashes attest only
those earlier candidates. The new wrappers compile against the archived
Beta 14 launcher and disposable guarded-server fixture, and startup refusal
is tested with disposable subprocesses. Neither final candidate is installed
or a production lifecycle adapter.

Pending transaction recovery now demands a separate
`resume_maintenance(source, attempt_id)` lifecycle operation. An adapter that
only offers fresh maintenance is refused before any rollback or code edit; a
returned lease for another attempt is refused as well. The disposable crash
tests provide an explicit fixture implementation. The production resume path
still needs to authenticate the original ticket and prove every writer stopped.

`pending_attempt_recovery.py` provides the first stopped-server recovery
boundary. It reads the private ticket, intent and pending journal with strict
identity checks, obtains the exclusive guarded-server lifetime lock plus the
admission/job locks, and requires a separately supplied local-listener absence
check. It returns the original ticket while retaining the lifetime lock; it
does not restart, clear markers, or modify code/data. Disposable tests refuse
an active guarded writer, a listener, a different attempt, and a terminal
journal. The macOS listener census and authenticated restart still belong to
the unfinished production lifecycle adapter.

`owned_guarded_lifecycle.py` now joins the retained Beta 14 Popen identity,
durable attempt, authenticated graceful stop, exclusive lifetime lock,
ticketed restart, authenticated server/worker status and terminal marker
finalization. It also exposes the separate stopped-attempt resume operation
required by the transaction. An end-to-end disposable signed transaction uses
this adapter for both commit and health-failure rollback while proving SQLite,
Ollama config and audio bytes unchanged. OS start/group and listener census
are mocked in that fixture because this runner cannot validate the owner's
macOS process inventory. This candidate is not imported by Beta 14 and does
not make installation available. A first signed guarded-server/bootstrap
installation, recovery of a still-running orphaned attempt, actual Mac process
lifecycle validation, real Ollama validation and a production release remain.

The first guarded bootstrap has a separate verification gate in
`bootstrap_release.py`. It pins the existing Manager publisher public key,
requires a production Ed25519 manifest explicitly attesting an isolated
rollback and a real macOS runtime check, accepts exactly the transformed
`server.py` and `launch_manager.py`, and compares both to the deterministic
preparers. It never writes either file. The private signing key remains on
the owner's Mac, and no such production manifest exists yet. The two-file
offline transaction and its crash recovery must be implemented and validated
before a bootstrap can be offered as one click.
The final guarded server refuses a stranded bootstrap intent when no valid
maintenance ticket exists; the final Beta 14 launcher refuses that intent
before spawning. A ticketed bootstrap health restart can still run under the
existing server lifetime guard. These checks are tested on disposable copies.

Signature verification now has a CryptoKit fallback in `ed25519_runtime.py`
for the owner's Mac when the `cryptography` Python package is absent. It uses
the same already-pinned public keys, verifies exact canonical message bytes,
and accesses no private key. Linux tests exercise the Python path; macOS CI
also forces the fallback and checks that a changed message is rejected. The
Swift verifier must be bundled with a future installable Manager candidate.
The macOS fixture exposed a worker-start and HTTP admission timing race. The
prospective lifecycle now waits for an authenticated worker before creating a
maintenance attempt and retries only a short transient admission-lock conflict
during cooperative rollback. It never falls back to a raw PID signal.

`bootstrap_transaction.py` now exercises the initial two-file swap on
disposable copies. It requires a separate offline lifecycle and matching
private bootstrap intent plus ticket, reuses the mandatory SQLite/config
backup and restoration drill, journals both file replacements, and restores
the original server and launcher if candidate health fails. A saved pending
attempt can resume only with its original identifier. A backup failure before
either swap restarts the originals. This has no production offline lifecycle,
no enabled UI request and no signed production release; an incomplete stage
  that cannot be authenticated remains blocked for manual recovery.
The bootstrap fixture now passes a genuinely signed two-file manifest through
the same verification path before the copy transaction. A changed signature
refuses before creating maintenance, and duplicate or malformed terminal
journal fields fail closed. No publisher private key is present in the test.
The pre-swap journal now records both original code digests. If a crash
interrupts the backup itself, recovery can prove that neither code file has
changed and restart the originals without trusting partial backup files.
The fixture also restores the exact original pair after interruption between
the server and launcher replacements; SQLite/config and other data bytes stay
unchanged. These are copy-only recovery tests, not a Mac installation.

`creative_install_controller.py` is the prospective parent-side entrypoint
for a single click after the guarded bootstrap. It refuses a server not owned
by this Manager instance before downloading, resumes a pending transaction
as the entire click, and otherwise passes a signed-channel download to the
existing transaction. It is not imported by the installed Beta 14, and the
current two-file bootstrap does not bundle this module or its dependencies.
The signed first bootstrap must ship those resources and the Swift verifier
before any real installation button is enabled.

`beta14_one_click_candidate.py` prepares a further pinned copy of the Beta 14
launcher and dashboard. Its localhost HTTP child authenticates the click and
records a request; the parent that retains the original server handle calls
the controller and exposes the terminal result. The patched archived app
passes its disposable smoke test, including rejection of an unauthenticated
install POST, and a request-handler fixture proves the parent dispatch. This
is a candidate only: the two-file bootstrap verifier does not accept this
launcher/dashboard pair, updater modules are not bundled, no button is active
on the owner's Mac, and a production Creative release has not been published.

The complete first-bootstrap release verifier now requires the guarded server,
the patched Beta 14 launcher and dashboard, all 17 transitive Python modules
used by the install controller, and the CryptoKit Swift verifier in one signed
archive. `bootstrap_full_release.py` validates an exact member list and each
signed digest before any extraction. This supersedes the earlier two-file
prototype as the intended release format. `bootstrap_full_transaction.py`
backs up the exact server, launcher and dashboard plus SQLite/config, drills
a separate SQLite/config restoration, journals every swap, and restores the
original code while removing the installed runtime if health fails. Disposable
tests cover commit, failed-health rollback and an interrupted partial switch;
all data-folder bytes remain unchanged. The offline first-bootstrap lifecycle
still needs to prove the old app/server stopped and to re-sign and validate
the modified macOS app. No production release or live installation exists.

The full bootstrap now also saves the complete stopped `.app` before a swap,
checks every file digest and mode, and drills a separate restoration. On
rollback it restores the app executable and its local code-signature resources
from that private copy, while refusing any unexpected new file. This protects
the exact original app if a later local re-sign changes more than the dashboard
and launcher. Copy-only tests simulate a changed native executable/signature;
the actual macOS signing and offline lifecycle remain unvalidated.

The consolidated `mac_final_readonly_probe.py` is prepared for the owner Mac.
It reads only the three pinned code/UI baselines, downloads hash-pinned public
preparers from one immutable GitHub commit, compiles the final candidates in
memory, and reports only whether a server, Manager, or port listener is seen.
It does not open the database/config/private key, stop processes or write to
the installation. Its coarse process census is diagnostic evidence, not yet a
safe offline lifecycle or authorization for installation.

On 29 October 2026 the owner reran the corrected probe on the Mac. It
recognized the original live server, Beta 14 launcher and dashboard and
compiled the final candidate hashes `e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27`,
`79130fbb4c0404c271c83242718945258e0f0dd8616cad61fb890228672dd2e4`,
and `43647e2449d4b7bfd6924502e728e8cf8bb5ebc0f7333d56d7e85bb0bbed1cb2`.
The server, Manager and port 8765 were all active. The probe did not stop
anything or access SQLite. The first earlier run refused an indentation in
the new recovery wrapper; that wrapper now derives the original indentation.

The first external bootstrap gate refuses those observed active conditions.
It never sends a signal to the old unguarded server. The copy transaction now
also backs up the complete `.app`, including its native executable and local
code signature, drills its restoration, and restores that exact app on failed
health. `offline_bootstrap_lifecycle.py` joins a private intent/ticket, an
exclusive lifetime lock, repeated offline process checks, local app signing,
ticketed owned candidate health, and terminal marker removal. A restored
original remains stopped and its existing app signature is checked without
re-signing. This lifecycle passes disposable fixtures, but its actual Mac
stop/restart, process census, code-signing and crash recovery are not yet
owner-validated; no production installer calls it and no release is signed.

`first_bootstrap_installer.py` now connects a fixed GitHub Pages bootstrap
channel to the full verifier, repeated offline gate, lifecycle and transaction.
It refuses the owner's current active server/Manager state before any network
request. The signed v2 manifest binds a single archive URL under
`manager-bootstrap`, and the downloader verifies the publisher and exact
active baseline before fetching the archive, rejecting redirects and size
changes. The entrypoint requires an explicit install flag; no production
manifest or archive has been published and it must not be run on the Mac yet.
Disposable tests cover the orchestration, signature-before-download order and
rollback. Actual owner-Mac runtime validation and signing with the existing
local Manager publisher key are still prerequisites.
On a repeat launch with a nonterminal journal, the entrypoint first verifies
the saved signed manifest against its saved original files and resumes the
same attempt without accessing the GitHub channel. A crash before the saved
manifest is complete still fails closed and needs a separate recovery path;
it must not be treated as an ordinary new installation.

`build_first_bootstrap_app.py` can package that entrypoint and its static
Python dependency closure into a separate Finder app built with macOS
`osacompile` and local ad-hoc `codesign`. Its AppleScript UI reports the
offline refusal in plain French. The app builder has a macOS-only disposable
bundle/signature test; the GitHub macOS runners have not completed it yet.
No installer app or bootstrap release is published, and the package itself
does not carry a publisher signing key or authorize a release.

`mac_disposable_app_signature_probe.py` is an optional owner-Mac rehearsal
before publication: it authenticates the same immutable read-only preparers,
copies the already installed Beta 14 app to a temporary directory, verifies
its original signature, signs the prepared launcher/dashboard in that copy,
then restores and verifies the copied original. It reads the source hashes
but does not run the server or open data. This rehearsal has not been run on
the owner's Mac and must not be described as passed.

The first owner rehearsal refused at `original_copy_verify`: the active app's
signature verified, but the copied `RapBrainManagerLegacy` shell launcher lost
its detached code-signing metadata. Full app inventory, private backup and
restoration now also record and restore bounded file extended attributes;
the disposable Mac probe preserves them as well. Linux tests check metadata
round trips, and a macOS fixture signs a shell helper to exercise detached
metadata. Actual owner copy validation must be repeated before installation.

Run tests: `python -m unittest discover -s manager-updater -p 'test_*.py' -v`.
