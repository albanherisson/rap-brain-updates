# Signed transaction integration — lab v2 (2026-10-25)

A locally executed test harness now joins:

1. Ed25519 publisher trust anchor pinned to `LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY=`.
2. Canonical JSON payload validation, strict schema and `install_allowed: false`.
3. ZIP size and SHA-256 verification, one permitted entry `Contents/Resources/manager.py`.
4. Single-file transactional replacement and recovery in a marked disposable `Synthetic Manager.app`.

**Local test result: 19/19 successful** (10 existing transaction tests and 9 new integration/rejection tests). The integration suite signs using a **temporary test key**, not the real publisher key; signature verification is injected for tests. The macOS Swift CryptoKit verifier source is included in the downloadable lab v2 artifact, but real-Mac end-to-end verification is still required.

**Safety boundary:** This is NOT a working installer. The real `~/Applications/Rap Brain Manager.app` is explicitly excluded. No production download or installation is allowed. No existing Manager app or Rap Brain data was modified.

Remaining: host this code in reviewable repository form, validate macOS Swift verifier using a real authorized signature, process lock, process stop/restart, health check, durable crash recovery, and tested auto rollback, before enabling production installation.
