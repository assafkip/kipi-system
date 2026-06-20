// capability-signer.swift - Secure-Enclave signer for capability approval tokens.
//
// The private key lives in the Secure Enclave (non-extractable) gated by Touch
// ID, so signing requires founder presence. `check` in capability-token.sh
// verifies the signature with the exported public key via openssl. This is the
// phase-2 forgery resistance: an agent that writes a token file cannot produce a
// valid signature. Spec: .prd-os/prds/prd-capability-token-signing-2026-06-16.md
//
// Subcommands:
//   init      provision (or reuse) the persistent biometry-gated SE key; export
//             the public key as SPKI PEM to ~/.claude/capability-token.pub
//   sign      read bytes on stdin, sign (Touch ID), print base64 DER signature
//   pubkey    print the persistent key's SPKI PEM public key
//   selftest  ephemeral SE key, no biometry/no Touch ID: print pubkey PEM + sig
//             so a harness can confirm SE-sign -> openssl-verify compatibility

import Foundation
import Security

let TAG = "com.kipi.capability-token".data(using: .utf8)!
let HOME = FileManager.default.homeDirectoryForCurrentUser
let PUBPATH = HOME.appendingPathComponent(".claude/capability-token.pub")

// SPKI DER prefix for an uncompressed P-256 (prime256v1) EC public key. The
// SecKey external representation is the raw 65-byte X9.63 point; openssl wants
// SubjectPublicKeyInfo, so we prepend this fixed header. (codex finding: pin the
// exact encoding so Swift output verifies under openssl.)
let SPKI_P256_PREFIX: [UInt8] = [
  0x30,0x59,0x30,0x13,0x06,0x07,0x2a,0x86,0x48,0xce,0x3d,0x02,0x01,
  0x06,0x08,0x2a,0x86,0x48,0xce,0x3d,0x03,0x01,0x07,0x03,0x42,0x00
]

func die(_ m: String, _ code: Int32 = 1) -> Never {
  FileHandle.standardError.write((m + "\n").data(using: .utf8)!)
  exit(code)
}

func spkiPEM(_ pub: SecKey) -> String {
  var err: Unmanaged<CFError>?
  guard let raw = SecKeyCopyExternalRepresentation(pub, &err) as Data? else { die("pubkey export failed") }
  var der = Data(SPKI_P256_PREFIX); der.append(raw)
  let b64 = der.base64EncodedString(options: [.lineLength64Characters, .endLineWithLineFeed])
  return "-----BEGIN PUBLIC KEY-----\n\(b64)\n-----END PUBLIC KEY-----\n"
}

func access(biometry: Bool) -> SecAccessControl {
  var err: Unmanaged<CFError>?
  let flags: SecAccessControlCreateFlags = biometry ? [.privateKeyUsage, .biometryCurrentSet] : [.privateKeyUsage]
  guard let ac = SecAccessControlCreateWithFlags(
    kCFAllocatorDefault, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, flags, &err) else { die("access-control creation failed") }
  return ac
}

func createKey(permanent: Bool, biometry: Bool) -> SecKey {
  var err: Unmanaged<CFError>?
  let priv: [String: Any] = [
    kSecAttrIsPermanent as String: permanent,
    kSecAttrApplicationTag as String: TAG,
    kSecAttrAccessControl as String: access(biometry: biometry),
  ]
  let attrs: [String: Any] = [
    kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
    kSecAttrKeySizeInBits as String: 256,
    kSecAttrTokenID as String: kSecAttrTokenIDSecureEnclave,
    kSecPrivateKeyAttrs as String: priv,
  ]
  guard let key = SecKeyCreateRandomKey(attrs as CFDictionary, &err) else {
    die("SE key creation failed: \(err!.takeRetainedValue())")
  }
  return key
}

func persistentKey() -> SecKey? {
  let q: [String: Any] = [
    kSecClass as String: kSecClassKey,
    kSecAttrApplicationTag as String: TAG,
    kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
    // Only ever match a Secure-Enclave key: a pre-seeded same-tag SOFTWARE key
    // must never be adopted as the production signer. (codex-adversarial finding)
    kSecAttrTokenID as String: kSecAttrTokenIDSecureEnclave,
    kSecReturnRef as String: true,
  ]
  var out: CFTypeRef?
  return SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess ? (out as! SecKey) : nil
}

func sign(_ key: SecKey, _ data: Data) -> Data {
  var err: Unmanaged<CFError>?
  guard let sig = SecKeyCreateSignature(key, .ecdsaSignatureMessageX962SHA256, data as CFData, &err) as Data? else {
    die("sign failed: \(err!.takeRetainedValue())")
  }
  return sig
}

let args = CommandLine.arguments
guard args.count >= 2 else { die("usage: capability-signer {init|sign|pubkey|selftest}", 2) }

switch args[1] {
case "init":
  // Idempotent: reuse an existing key, never create a duplicate.
  let key = persistentKey() ?? createKey(permanent: true, biometry: true)
  guard let pub = SecKeyCopyPublicKey(key) else { die("init: no public key") }
  try? FileManager.default.createDirectory(at: PUBPATH.deletingLastPathComponent(), withIntermediateDirectories: true)
  do { try spkiPEM(pub).write(to: PUBPATH, atomically: true, encoding: .utf8) }
  catch { die("init: cannot write pubkey: \(error)") }
  print("init: provisioned; public key at \(PUBPATH.path)")

case "sign":
  guard let key = persistentKey() else { die("sign: no key; run `capability-signer init` first") }
  let input = FileHandle.standardInput.readDataToEndOfFile()
  print(sign(key, input).base64EncodedString())

case "pubkey":
  guard let key = persistentKey(), let pub = SecKeyCopyPublicKey(key) else { die("pubkey: no key") }
  print(spkiPEM(pub), terminator: "")

case "selftest":
  // Ephemeral, non-biometry SE key: no Touch ID, no persistent state. Proves SE
  // sign works AND that the SPKI PEM + DER signature verify under openssl.
  let key = createKey(permanent: false, biometry: false)
  guard let pub = SecKeyCopyPublicKey(key) else { die("selftest: no public key") }
  let msg = "capability-signer-selftest".data(using: .utf8)!
  print(spkiPEM(pub), terminator: "")
  print("---SIG---")
  print(sign(key, msg).base64EncodedString())

default:
  die("usage: capability-signer {init|sign|pubkey|selftest}", 2)
}
