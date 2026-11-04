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
its macOS job must pass before the capability can advance. A real disposable
parent/pipe exit test now runs on macOS as well. This container hides its own
child processes from `ps`, so that one integration case is skipped locally;
it is not counted as a local process proof.

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
not a production release; a signed capability installer and macOS rehearsal
are still missing.
The helper now records a small private terminal result after the HTTP parent
exits; a pending maintenance ticket is displayed as requiring a check instead
of reporting a false success. A crash before the report still needs a
dedicated recovery entrypoint and macOS process tests.
`manager_update_recovery.py` is a separate offline entrypoint for the existing
attempt. It reads the original private intent and signed stage, checks the
attempt identity and any saved release, and either aborts unchanged
pre-journal code, resumes a nonterminal journal, or verifies terminal code,
application inventory and signature before clearing its original ticket.
The committed receipt is reconstructed if the crash preceded its write.
Tests cover committed, rolled-back and tampered terminal states with synthetic
SQLite/configuration. Capability packaging and macOS process validation are
still missing; this path is not installed.
The unchanged-code abort now creates its private attempt directory before the
macOS lifecycle verifies the application signature. A disposable lifecycle
test covers the ticket cleanup and confirms synthetic data is unchanged.

`manager_helper_bundle.py` now assembles the exact 41-file external helper
candidate deterministically (40 Python modules and the existing CryptoKit
verifier). `manager_helper_release.py` authenticates a separate Manager-key
signed manifest and exact archive before creating a private helper directory;
extra members, changed bytes and stale signatures are rejected on copies.
The private staged helper retains the signed manifest; the candidate Manager
verifies every helper file again before importing the parent module. A changed
file blocks the action. Expiry limits first staging; an already installed
helper remains authenticated against the original signed hashes. The signed capability
installer must include the verifier and its imports in the app bundle.
No production helper manifest is signed or published. Staging this helper
does not install or authorize the Manager UI; a signed one-time capability
installer still has to deliver both the helper and reviewed app changes.
`manager_capability_bundle.py` now builds one deterministic, unsigned
candidate archive from the pinned post-Creative Beta 14 launcher/dashboard,
the external helper archive, and exactly ten additional app verifier modules.
It rejects a changed baseline and contains no database, Ollama configuration,
library or private key. The owner Beta 14 ZIP smoke passes locally. This is
packaging input only: no production capability manifest is signed or published.

The one-time capability now has a strict, read-only verifier
(`manager_capability_release.py`), an offline transaction
(`manager_capability_transaction.py`), and a Finder builder/entrypoint. The
verifier requires two Manager-key signatures, exact code-only members, fresh
authorization, the pinned post-Creative launcher/dashboard and guarded server.
The transaction saves and drills a complete app backup plus SQLite/Ollama
configuration before staging the private helper or replacing code. It signs
the app locally, verifies the signed candidate, restores the exact original
app on failure, and resumes an interrupted attempt from its saved signed
release without network access. Disposable synthetic commit, failure and
interruption tests pass. The Finder builder and real macOS codesign tests
passed in CI, including signature-preserving rollback on a disposable app.
The reviewed 116,565-byte candidate is pinned on the draft branch at
`19d84a4db0713a658265df3358a68c1adc6388be`, SHA-256
`963ca5733de48d7d336b1c214a0b8f308aa582aa3484a5ae51769daafe0cf8a7`.
`mac_sign_manager_capability.py` checks the owner's launcher/dashboard/server
and app signature, then prepares both Manager-signed manifests and one public
ZIP using the existing private Manager key. It never exports the private seed
or installs code. No production manifest exists yet; the key is only on the
owner's Mac. The Finder app must not be offered as a working updater before
the public ZIP is signed, verified and placed at the fixed channel.
Before any live code replacement, the Finder installer now rehearses both a
successful signed app change and an exact signature-preserving rollback on
separate copies of the owner's app. Its only SQLite and Ollama configuration
are synthetic. A failed rehearsal refuses the live transaction; pending
recovery still uses its original saved signed release and no network request.

## Remaining implementation gates

1. On the owner's Mac, verify the pinned candidate and unchanged installed
   baseline, then use the existing Manager key to sign the **public** package.
   No private key or original library may be uploaded.
2. Verify the received public ZIP and publish only its two exact signed files
   to the fixed GitHub channel. Run the Finder capability installer once,
   with Rap Brain and the Manager closed, and check its committed receipt.
3. Open the Manager and exercise a published general update on a disposable
   copy before making any general release available for the owner's active
   app. Check HTTP health, interrupted phases and exact rollback there.

The release verifier alone does not authorize any write to the installed app.
The Creative-specific button remains the only production one-click path today.
