import Foundation
import CryptoKit
import Darwin

// Éditeur local seulement : la clé privée ne doit jamais quitter le Mac.
let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/RapBrainManager", isDirectory: true)
let privateURL = support.appendingPathComponent("publisher_ed25519.key")
func fail(_ message: String) -> Never { fputs("ERREUR: \(message)\n", stderr); exit(1) }
func existing() -> Curve25519.Signing.PrivateKey {
  guard let data = try? Data(contentsOf: privateURL), data.count == 32,
        let key = try? Curve25519.Signing.PrivateKey(rawRepresentation: data) else {
    fail("Clé privée absente ou invalide.")
  }
  return key
}
let a = CommandLine.arguments
if a.count < 2 { fail("Usage : swift publisher_key.swift init | public | sign FICHIER") }
switch a[1] {
case "init":
  do {
    try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    if FileManager.default.fileExists(atPath: privateURL.path) {
      print("Clé existante préservée. Publique : " + existing().publicKey.rawRepresentation.base64EncodedString())
    } else {
      let key = Curve25519.Signing.PrivateKey()
      let data = key.rawRepresentation
      let fd = open(privateURL.path, O_WRONLY | O_CREAT | O_EXCL, 0o600)
      if fd < 0 { fail("Création exclusive impossible") }
      let n = data.withUnsafeBytes { write(fd, $0.baseAddress!, $0.count) }
      _ = fsync(fd); _ = close(fd)
      if n != data.count { fail("Écriture incomplète") }
      print("Clé privée conservée sur ce Mac. Publique : " + key.publicKey.rawRepresentation.base64EncodedString())
    }
  } catch { fail("Création impossible : \(error)") }
case "public": print(existing().publicKey.rawRepresentation.base64EncodedString())
case "sign":
  if a.count != 3 { fail("Fichier à signer manquant") }
  guard let bytes = try? Data(contentsOf: URL(fileURLWithPath: a[2])), !bytes.isEmpty else { fail("Fichier illisible") }
  do { print(try existing().signature(for: bytes).base64EncodedString()) }
  catch { fail("Signature impossible") }
default: fail("Commande inconnue")
}
