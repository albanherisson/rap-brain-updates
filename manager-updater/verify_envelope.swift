import Foundation
import CryptoKit

// Trust anchor compiled into the updater. Never obtain it from remote metadata.
let pinnedKey = "LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY="
func reject(_ reason: String) -> Never { fputs("REJECT: \(reason)\n", stderr); exit(1) }
let args = CommandLine.arguments
guard args.count == 3 else { reject("usage: swift verify_envelope.swift SIGNATURE_BASE64 CANONICAL_PAYLOAD_FILE") }
guard let keyBytes = Data(base64Encoded: pinnedKey), keyBytes.count == 32,
      let pub = try? Curve25519.Signing.PublicKey(rawRepresentation: keyBytes) else { reject("Bad pinned key") }
guard let sig = Data(base64Encoded: args[1]), sig.count == 64 else { reject("Invalid signature") }
guard let bytes = try? Data(contentsOf: URL(fileURLWithPath: args[2])) else { reject("Missing signed payload") }
guard pub.isValidSignature(sig, for: bytes) else { reject("Publisher signature mismatch") }
print("Publisher signature valid")
