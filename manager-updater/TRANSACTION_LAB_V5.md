# Synthetic transaction laboratory V5 — verified 25 Oct 2026

**46/46 tests passed** locally using `python3 -m unittest discover -q` (the previous 35 plus 11 tests of commit and cleanup recovery).

## New capability

The synthetic updater now supports an explicit **finalization phase** after a simulated successful launch/health probe. It persists a `committed` transaction marker **before** deleting its old backup, so a crash during cleanup can be retried safely. A finalized transaction does not allow rollback and the state can be removed for a subsequent synthetic update. Interruption and unsafe symlink-backup cases are covered by tests.

The lab remains limited to `Synthetic Manager.app` with a disposable fixture marker. **It does not modify, install into, or provide access to the user's actual Manager or Rap Brain data.** The production updater is still disabled.

**Reference archive:** `Rap_Brain_Manager_Transaction_Lab_v5.zip`, SHA-256: `891adee6d59ddbd9d7dd77a763de1057e816791dbc6a24b0bef27ea3f34be992`. The archive is distributed separately in the associated conversation; it is **not** a release or a required user download.

## Blocking production requirements

1. Real publisher-signed release envelope for a concrete archive (not just publisher identity proof).
2. Pinned CryptoKit verification against that release on user's Mac.
3. Safe HTTPS downloader enforcing host/redirect constraints, size limits, and hash verification.
4. macOS process lifecycle (avoid duplicate Manager processes), independent installer process, health probe and automatic rollback.
5. A durable crash recovery path, and full preservation of custom icon, permissions and data.
6. A copy-only dry run on the actual installed bundle structure, then a separately approved production deployment.

The editor identity challenge was verified by the user on macOS. That confirms the signing identity only, **not the production updater's operational security**.
