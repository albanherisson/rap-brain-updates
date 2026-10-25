import Foundation
import CryptoKit

// Read-only, isolated publisher identity validation on macOS.
// No file writes, network, application launch, or update installation.
let keyText = "LwtwcLI4RHATP4OXL1UDlnXg9WUdSupoD8s25krcXMY="
let signatureText = "bGMLqcOHwRtcmCtDvQFIhrswXqtXmhQEfrdZOWuIRSCvaHbNEXHCUWzIKuYEW5t3Asf2oZfnx4o9fGcO1VFyCA=="
let challenge = [
 "RAP-BRAIN-PUBLISHER-IDENTITY-PROOF-v1",
 "publisher=albanherisson",
 "channel=rap-brain-updates",
 "purpose=verify-ownership-of-ed25519-publishing-key-only",
 "install_allowed=false",
 "nonce=b03c3f49c0a7af90816513f08226edbd"
].joined(separator:"\n") + "\n"
func fail(_ message: String) -> Never { fputs("ECHEC: \(message)\n", stderr); exit(1) }
guard let keyData=Data(base64Encoded: keyText), keyData.count == 32,
      let key=try? Curve25519.Signing.PublicKey(rawRepresentation: keyData),
      let signature=Data(base64Encoded: signatureText), signature.count==64 else { fail("clé ou signature invalide") }
let original=Data(challenge.utf8)
guard key.isValidSignature(signature, for: original) else { fail("signature légitime rejetée") }
var altered=original
altered[0] ^= 0x01
guard !key.isValidSignature(signature, for: altered) else { fail("message modifié accepté !") }
print("SUCCES: signature éditeur authentique acceptée")
print("SUCCES: message altéré refusé")
print("SUCCES: aucune application ou donnée modifiée")
