import Foundation
import CryptoKit

// Public key pinned at build time. Never load an update authority from the catalog itself.
let publisherKeyB64 = "LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY="
func refuse(_ message: String) -> Never { fputs("REFUS: \(message)\n", stderr); exit(1) }
let args = CommandLine.arguments
guard args.count == 3 else { refuse("Usage: swift verify_publisher_challenge.swift SIGNATURE_B64 FICHIER") }
guard let publicBytes = Data(base64Encoded: publisherKeyB64),
      publicBytes.count == 32,
      let publicKey = try? Curve25519.Signing.PublicKey(rawRepresentation: publicBytes) else { refuse("Trusted key malformed") }
guard let signature = Data(base64Encoded: args[1]), signature.count == 64 else { refuse("Bad signature length or base64") }
guard let challenge = try? Data(contentsOf: URL(fileURLWithPath: args[2])) else { refuse("Challenge unavailable") }
guard challenge.starts(with: Data("RAP-BRAIN-PUBLISHER-IDENTITY-PROOF-v1\n".utf8)),
      challenge.contains(Data("install_allowed=false\n".utf8)) else { refuse("Unexpected challenge or installation flag") }
guard publicKey.isValidSignature(signature, for: challenge) else { refuse("Signature does not match the PINNED publisher key") }
print("✅ Publisher Ed25519 signature valid (Apple CryptoKit). NO INSTALLATION.")
