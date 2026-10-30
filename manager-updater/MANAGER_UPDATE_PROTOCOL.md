# Manager update protocol — implementation checkpoint

The owner installed the guarded first bootstrap and Creative Engine P8 on the
Mac on 30 October 2026; the original library and analyses remained visible.
The generic Beta 14 “Installer / Mettre à jour” tile is still disabled. Its
label must not be changed to claim that general installation works.

`manager_update_release.py` is the **read-only** part of the next updater. It
pins the existing Manager publisher identity, authenticates a fresh Ed25519
manifest before fetching an archive, checks exact archive and member hashes,
restricts targets to `server.py` and reviewed Manager app resources, rejects
data/library/configuration paths, and checks each installed baseline. Tests
cover payload tampering, replay, alternate hosts, extra archive members and
live baseline drift. There is no production `manager-stable` publication yet.

## Remaining implementation gates

1. Build a transaction that uses the current guarded lifetime lock and
   maintenance ticket, verifies no analysis or audio job is active, backs up
   the entire app plus SQLite/config, drills restoration on a separate copy,
   and journals every phase before replacement. Keep the live database and
   configuration outside the signed archive and never restore over them
   automatically.
2. The HTTP child may only record an authenticated request. The parent owns
   the server process. A Manager app update requires a separately signed,
   locally launched helper to own the handoff while the Manager exits. It must
   authenticate the exact old process, stop only that process, hold exclusion,
   replace code atomically, sign the changed app on macOS, start the reviewed
   candidate, check authenticated health, and restore exact backup on failure.
   Recovery after a crash must resume the original journal without pulling a
   fresh release or silently starting a second attempt.
3. Rehearse success, failed health, interrupted phases and exact rollback on
   disposable macOS copies, including the app's extended attributes and a
   synthetic SQLite/config. Reject a busy or unowned server. Verify signed
   channel bytes, publisher key and release expiry independently.
4. Publish a production release only after the copy rehearsals and sign it
   with the existing Manager key on the owner's Mac. Then enable the generic
   button through a signed app update and validate it once on the owner's Mac.

The release verifier alone does not authorize any write to the installed app.
The Creative-specific button remains the only production one-click path today.
