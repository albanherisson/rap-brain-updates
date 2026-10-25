# Signed transaction lab V4 — combined test pipeline

Date: 25 October 2026

**35/35 distinct local tests passed** in a disposable synthetic fixture (previous 28 plus 7 new integration scenarios).

Previously, signature checks and recovery checks had only been tested in separate flows. In V4, `combined_pipeline_lab.py` verifies the signed catalog and the ZIP before any mutation, extracts a single permitted script into temporary storage, then runs the synthetic transactional switch with a simulated application launch and health probe.

Integration scenarios cover:
- valid signature / archive and healthy synthetic restart;
- valid signature and launch failure -> automatic rollback;
- valid signature and failed health probe -> automatic rollback;
- tampered signed payload -> reject before launch or write;
- concurrent update attempt -> reject before launch or write;
- altered ZIP -> reject before launch or write;
- `install_allowed: true` -> reject by design.

Local packaged reference: `Rap_Brain_Manager_Transaction_Lab_v4.zip`.
SHA-256: `28553a36f0b729a650f8dc26d9139008a6fc2fdf638b8aa31c5a006cbe990ff2`.

**Scope and limitations:** This is still a *non-installable laboratory*. It uses a temporary test key and injected verifier for unit tests; the real publisher key was separately verified using macOS CryptoKit in an identity challenge but not yet for a signed release archive. Mock callbacks stand in for macOS application process management. There is no production downloader, no durable cross-reboot updater and no production application modification. The actual `~/Applications/Rap Brain Manager.app`, custom icon, and Rap Brain data remain untouched.
