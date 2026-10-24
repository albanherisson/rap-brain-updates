import Foundation
import CryptoKit
func die(_ s: String) -> Never { fputs("REFUS: \(s)\n", stderr); exit(1) }
let a = CommandLine.arguments
guard a.count == 4 else { die("usage: swift verify_signature.swift PUBLIC_KEY_BASE64 SIGNATURE_BASE64 PAYLOAD_FILE") }
guard let pub = Data(base64Encoded:a[1]), pub.count == 32,
      let sig = Data(base64Encoded:a[2]), sig.count == 64,
      let key = try? Curve25519.Signing.PublicKey(rawRepresentation:pub),
      let data = try? Data(contentsOf: URL(fileURLWithPath:a[3])) else { die("Invalid key, signature or file") }
guard key.isValidSignature(sig, for:data) else { die("Ed25519 signature mismatch") }
print("Ed25519 OK")
