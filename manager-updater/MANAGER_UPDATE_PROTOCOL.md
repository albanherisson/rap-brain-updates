# Manager update protocol — implementation checkpoint

The owner installed the guarded first bootstrap and Creative Engine P8 on the
Mac on 30 October 2026; the original library and analyses remained visible.
The generic Beta 14 “Installer / Mettre à jour” tile is still disabled. Its
label must not be changed to claim that general installation works.

`manager_update_release.py` is the **read-only** part of the next updater. It
pins the existing Manager publisher identity, authenticates a fresh Ed25519
manifest before fetching an archive, checks exact archive and member hashes,
restricts targets to `server.py` and reviewed Manager app resources, rejects
data/library/configuration paths, and checks each installed baseline including
the server even for app-only releases. Before local signing, the lifecycle
checks that every unselected app file still matches the complete backup. Tests
cover payload tampering, replay, alternate hosts, extra archive members and
live baseline drift. There is no production `manager-stable` publication yet.

`manager_update_rehearsal.py` applies signed code to a disposable copy and
checks an exact app/server restore. `manager_update_transaction.py` journals
the general update, saves a complete app backup and a fresh SQLite/config
backup with restore drill, checks active jobs, refuses concurrent unfinished
updates, and restores exact code after failed health. It **refuses without a
reviewed lifecycle**. Disposable tests cover commit, rollback, crash recovery,
replay and missing lifecycle. No installed Manager calls this transaction.

`manager_offline_lifecycle.py` now adapts the existing exclusive lifetime
lock, private maintenance ticket, local app signing, owned candidate restart
and exact restored-app signature verification to a general signed release.
Disposable tests cover terminal ticket cleanup for both commit and failed
health rollback. This adapter has not yet passed macOS code-signing or real
process tests and is not connected to the installed Manager.
The macOS CI suite now includes a disposable, genuinely code-signed app test
that forces failed health and checks exact signature-preserving restoration;
its macOS job must pass before the capability can advance.

An unconnected handoff prototype now stages the signed release in a private
directory, binds the Manager parent's retained server handle, creates the
existing maintenance ticket, and stops that exact idle server cooperatively.
The external helper requires a nonce on an inherited pipe, proves the parent
actually exited, then resumes the same ticket and transaction. It can restart
unchanged original code for a failed pre-journal validation. These paths have
disposable unit tests only. A refused stop leaves its maintenance marker for
authenticated recovery, so this prototype must not be enabled as a button.
The helper and its dependencies also require a reviewed, signed deployment
outside the replaceable app bundle. The installed Beta 14 has none of this.
The pinned `manager_update_ui_candidate.py` now prepares a disposable copy of
the previously installed bootstrap launcher/dashboard. Its authenticated HTTP
request is handed to the parent that retains the owned server handle; the
parent exits after releasing the helper pipe. The copy smoke rejects a POST
without a token and leaves a synthetic server unchanged. This candidate is
not a production release and the helper bundle/recovery packaging is missing.
The helper now records a small private terminal result after the HTTP parent
exits; a pending maintenance ticket is displayed as requiring a check instead
of reporting a false success. A crash before the report still needs a
dedicated recovery entrypoint and macOS process tests.
`manager_update_recovery.py` is a separate offline entrypoint for an existing
nonterminal attempt. It reads the original private intent and signed stage,
checks the attempt identity and any saved release, and either aborts unchanged
pre-journal code or resumes the original journal. Its tests use synthetic
SQLite/configuration. Terminal-journal cleanup, capability packaging and
macOS process validation are still missing; it is not installed.

## Remaining implementation gates

1. Review the transaction and exercise signing, authenticated HTTP health,
   interruption and rollback with the real macOS app on disposable copies.
   Keep the live database and configuration outside the signed archive and
   never restore over them automatically.
2. Wire an authenticated request from the HTTP child to the parent with the
   retained Popen handle. Package and verify the external helper and all of
   its imports outside the app being replaced; exit the parent after handing
   off the lifetime lock. Provide a safe recovery entrypoint for failed stop,
   timeout and interrupted phases, without pulling a fresh release or
   silently starting a second attempt. Exercise actual process ownership and
   exclusion on disposable macOS copies.
3. Rehearse success, failed health, interrupted phases and exact rollback on
   disposable macOS copies, including the app's extended attributes and a
   synthetic SQLite/config. Reject a busy or unowned server. Verify signed
   channel bytes, publisher key and release expiry independently.
4. Publish a production release only after the copy rehearsals and sign it
   with the existing Manager key on the owner's Mac. Then enable the generic
   button through a signed app update and validate it once on the owner's Mac.

The release verifier alone does not authorize any write to the installed app.
The Creative-specific button remains the only production one-click path today.
