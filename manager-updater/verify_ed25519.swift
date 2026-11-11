import Foundation
import CryptoKit

guard CommandLine.arguments.count == 4,
      let publicBytes = Data(base64Encoded: CommandLine.arguments[1]),
      let signature = Data(base64Encoded: CommandLine.arguments[2]),
      publicBytes.count == 32, signature.count == 64,
      let message = try? Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[3])),
      let key = try? Curve25519.Signing.PublicKey(rawRepresentation: publicBytes),
      key.isValidSignature(signature, for: message) else {
    exit(1)
}
