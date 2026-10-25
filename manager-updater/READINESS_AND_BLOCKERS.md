# Stable Manager updates — current gated state (25 Oct 2026)

## Confirmed on owner's Mac

- Installed Manager's repaired launcher opens Safari and serves its UI.
- Publisher Ed25519 identity challenge accepted by Apple CryptoKit; altered challenge rejected.
- Genuine, publisher-signed 1.0.6 **lab** archive verified using CryptoKit, ZIP digest checked.
- A disposable complete copy passed a 22-file byte-for-byte restoration drill.
- An independent dummy HTTP process passed restart and failure-triggered rollback drills.
- The verified archive contained the **same** installed manager.py; this is not evidence that a changed release can be installed.

## Newly implemented in GitHub (NOT installed on owner's Mac)

- Strict JSON parser rejecting duplicate signed fields and nonfinite/floating-point values.
- Strict ZIP gate enforcing the single allowed manager.py entry, rejecting symlinks, traversal, duplicates, oversize and corrupt files.
- Read-only catalog inspector requiring ZIP on CLI and restricting distribution URLs to the official repository or Pages.
- Unit test suites for catalog, ZIP and JSON security.
- GitHub Actions workflow for Python regression tests and macOS CryptoKit challenge.

**CI run status remains unconfirmed**. A successful commit to GitHub is not proof GitHub Actions actually ran or passed.

## Release blockers, in order

1. Re-run GitHub Actions Python/macOS workflow and confirm both job conclusions are success.
2. Prepare a harmless but genuinely distinct candidate; sign *on owner's Mac* using publisher private key, never sharing or uploading key.
3. Verify signed candidate independently with pinned CryptoKit key, ZIP constraints and hash; replace in a disposable copy only, induce failed health check and prove rollback.
4. Build a minimal external supervisor with durable lock/journal, OS process start-time identity and controlled shutdown on a disposable app; require successful health-check restart.
5. Only after explicit authorization, update a small replaceable component of the installed app while preserving custom icon, resources, and user data. Installation remains disabled now.

Never treat `install_allowed: false` as authorization to install. Never modify `~/Downloads/rap-brain` or `~/Applications/Rap Brain Manager.app` as part of lab tests.
