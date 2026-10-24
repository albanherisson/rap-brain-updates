# Offline validation workflow

The private signing key stays on the publisher's Mac.

Use `publisher_key.swift init` **on the Mac** to initialize the key, `publisher_key.swift public` to export the public key, and `publisher_key.swift sign FILE` to sign a canonical payload.

`prepare_manifest.py` writes a catalog with `install_allowed: false`. Validate it with:

```sh
python3 publisher/validate_catalog.py --catalog candidate.json --public-key '<PUBLIC BASE64 KEY>' --archive Rap_Brain_Manager_example.zip
```

Verification uses Apple's CryptoKit via `verify_signature.swift`, then checks the actual ZIP size and SHA-256. Never publish the private key or use the non-installable lab catalog to trigger an installation. The real Manager updater and a durable, pinned publisher identity remain future work.
