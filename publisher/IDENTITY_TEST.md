# Publisher identity test — pinned key

**Status: identity validation only. No signed installable release exists.**

This challenge confirms that the private Ed25519 key on the publisher's Mac matches the permanently pinned public key:

`LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY=`

- The `docs/publisher-challenge.txt` content is public and contains `install_allowed=false`.
- The publisher signs the EXACT BYTES of the challenge on the publisher Mac using the existing local `publisher_key.swift`; only the detached signature is shared.
- This Swift verifier uses macOS Apple CryptoKit and a public key embedded in its source. It must fail for an altered challenge or another publisher key.
- This does not authorize installation, configure the running Manager, or prove any application bundle is safe.
- Never upload `publisher_ed25519.key` (private key).
