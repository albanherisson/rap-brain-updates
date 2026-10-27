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

## Next evidence needed

The earlier source review deliberately omitted `server.py` because it might
contain credentials. Do not request the unredacted file or upload the data folder.
`mac_server_structure.py` reads only this Python source, removes comments and
literal values (apart from a tiny fixed lifecycle vocabulary), and copies an
AST rendering to the macOS clipboard. It does not import or execute the server,
open SQLite, write reports, or modify the installation. The output is structural
review material and is intentionally not runnable replacement code.

After reviewing that structure: integrate the existing Beta14 launcher/UI with
the real maintenance/health/recovery mechanism, validate on a disposable copy,
resolve real Ollama generation, and only then sign an eligible production release
with the existing Creative Engine publisher key on the owner's Mac.

Run tests: `python -m unittest discover -s manager-updater -p 'test_*.py' -v`.
