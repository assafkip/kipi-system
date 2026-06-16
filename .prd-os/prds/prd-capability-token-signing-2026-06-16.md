---
id: prd-capability-token-signing-2026-06-16
title: Capability Token Signing
status: approved
created_at: 2026-06-16T04:58:02Z
updated_at: 2026-06-16T05:02:47Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-capability-token-signing-2026-06-16-findings.jsonl
codex_reviewed_at: 2026-06-16T05:00:48Z
---

# Capability Token Signing

## Problem

Phase 1 (prd-capability-approval-token-2026-06-16) left one hole open, tracked as its finding-3: an agent with filesystem write can `touch ~/.claude/approvals/<hash>.token` and self-approve, bypassing `mint`. Phase 1 only closed the approval window, not forgery. The phase-1 token is a plain file: its existence is its authority, and on a single-user box the agent can write that file.

Measurable: today a token is honored on existence alone, so `touch <hash>.token` grants approval. Target: a token is honored only with a valid signature from a key whose use requires founder presence (Touch ID), which the agent cannot produce.

Prior art: this is the askpass/keychain-signed evolution noted in phase 1. Grounding facts: phase-1 threat model is the confused agent (PocketOS 2026-05-17); a standalone Swift probe confirmed an ad-hoc (unsigned) `swiftc` binary can create, sign with, and verify a Secure Enclave P-256 key on this host.

## Goals

- A token is accepted only with a valid signature over a domain-separated payload from the trusted key
- The signing key lives in the Secure Enclave with a biometry (Touch ID) access control, so signing requires founder presence and the private key is non-extractable
- `check` verifies with the public key (no auth, no prompt on the hot path) and verifies BEFORE finalizing allow
- Fail closed with no downgrade: a missing/invalid signature, a missing/altered public key, or any verify error denies
- Pluggable signer backend so sign+verify+reject is testable without Touch ID (software EC key in tests, Secure Enclave in production)

## Non-goals

- Defending against an adversary who deletes or swaps the trusted public key. A sophisticated adversary could mount that downgrade/tamper on a single-user box; the confused-agent threat does not. `check` fails closed (missing/altered pubkey denies, never downgrades). Documented residual.
- Running the agent as a separate user or sandbox (the only true same-host fix; bigger environmental change, out of scope)
- Changing the phase-1 hash, atomic-consume, TTL, or audit-log behavior

## Proposed approach

Tokens carry a signature. Private key: Secure Enclave, Touch-ID gated. Verification: exported public key.

Canonical signed payload (domain-separated, versioned): the ASCII string `capability-token.v1\n<hash>\n<expiry>`. Crypto is pinned: ECDSA over P-256, SHA-256, DER-encoded signature, base64 in the token file. Swift `SecKeyCreateSignature(.ecdsaSignatureMessageX962SHA256)` emits DER, which `openssl pkeyutl`/`openssl dgst -verify` accepts with the exported SPKI public key.

1. `capability-signer` (Swift, compiled at install with `swiftc`):
   - `init`: create a PERSISTENT SE P-256 key, `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` + access control `[.privateKeyUsage, .biometryCurrentSet]`, stable application tag `com.kipi.capability-token`; idempotent (reuse if present, never duplicate); export the public key as PEM to `~/.claude/capability-token.pub`.
   - `sign`: read payload bytes on stdin, sign with the SE key (Touch ID prompt), print signature base64.
2. `capability-token.sh`:
   - `mint`: build the v1 payload, sign it via the configured signer, write a token: line 1 `expiry`, line 2 `signature-b64`. Signing failure means no token.
   - `check`: atomically claim the token, then VERIFY the signature over the rebuilt payload against `~/.claude/capability-token.pub` with openssl, and only on a valid signature AND unexpired expiry allow + finalize consume. Missing pubkey, missing/invalid signature, expired, or malformed denies (fail closed, no downgrade).
   - `CAPABILITY_SIGNER` selects the backend (default SE helper; tests set a software-key signer with a throwaway P-256 keypair, exercising the identical verify+reject path without Touch ID).

```
mint:  payload=v1|hash|expiry --SE sign (Touch ID)--> token={expiry, sig}
check: claim -> verify sig(payload) w/ pubkey
         valid + unexpired -> allow once (consume)
         invalid / missing sig / missing pubkey / expired / malformed -> deny
```

## Risks and rollback

- Public-key deletion/swap downgrade (documented non-goal). `check` denies on missing/unreadable pubkey, so deleting the pubkey yields denial-of-approval, not forged approval.
- Rollback modes (no silent downgrade to the forgeable phase-1 behavior): (a) SAFE rollback = remove the pubkey, which makes `check` deny all token approvals until re-provisioned (forgery resistance preserved, approvals paused); (b) FULL revert = restore the phase-1 `capability-token.sh` and remove the helper + pubkey, explicitly re-accepting the phase-1 forgery residual. The choice is the operator's; default is (a).
- Live activation changes UX: `kipi-approve` now prompts Touch ID; a misprovisioned key denies all approvals (fail closed). The live flip is gated on a successful `init`, which requires the founder's Touch ID and so is inherently a founder action.
- Install ordering recovery: init-then-deploy. If `init` fails, do not deploy (stay on phase 1). If deploy fails after a successful init, the pubkey exists but the old lib runs (still safe: old lib ignores signatures). A stale unsigned phase-1 token is rejected by the new signed-only check (ephemeral, 5-min TTL, no migration needed).
- SE signing requires Touch ID and is not automatable; covered by the standalone probe plus a manual check. The verify + forgery-rejection logic is fully automated via the software-key backend.

## Open questions

- Per-`kipi-approve` Touch ID vs a short grace window. Default: per-approval Touch ID (matches one-command-one-approval).

## Issues

```json
[
  {
    "id": "capability-token-sig-verify",
    "finding_id": "finding-2",
    "title": "capability-token.sh: domain-separated signed token, verify-before-allow, no-downgrade",
    "allowed_files": [
      "plugins/kipi-core/scripts/capability-token.sh",
      "plugins/kipi-core/scripts/test/test-capability-token-sig.sh"
    ],
    "required_checks": ["bash plugins/kipi-core/scripts/test/test-capability-token-sig.sh"],
    "bypass_check": "bash plugins/kipi-core/scripts/test/test-capability-token-sig.sh",
    "priority": "p1",
    "acceptance": "Token payload is the domain-separated, versioned string capability-token.v1 + LF + hash + LF + expiry. mint signs it; check atomically claims then verifies the ECDSA P-256/SHA-256 DER signature against the trusted public key BEFORE allowing. Negative cases all deny (fail closed, no downgrade): forged/unsigned token, wrong/swapped pubkey, missing pubkey, expired signed token, malformed token, replay after consume. Positive: a validly signed unexpired token is allowed exactly once then consumed. Tests use a software EC-key signer backend (no Touch ID)."
  },
  {
    "id": "capability-signer-se",
    "finding_id": "finding-4",
    "title": "capability-signer Swift Secure-Enclave helper + install provisioning",
    "allowed_files": [
      "plugins/kipi-core/scripts/capability-signer.swift",
      "plugins/kipi-core/scripts/install-capability-token.sh",
      "plugins/kipi-core/scripts/test/test-capability-signer.sh"
    ],
    "required_checks": ["bash plugins/kipi-core/scripts/test/test-capability-signer.sh"],
    "bypass_check": "bash plugins/kipi-core/scripts/test/test-capability-signer.sh",
    "priority": "p1",
    "acceptance": "capability-signer.swift compiles with swiftc. init creates a persistent SE P-256 key (ThisDeviceOnly, biometryCurrentSet, stable tag com.kipi.capability-token), idempotent (no duplicate keys), exports the public key as PEM. sign signs stdin bytes. The test proves swiftc compiles the helper and that an openssl-produced P-256/SHA-256 DER signature verifies with the exported-format public key (encoding compatibility), since the Touch-ID SE signing path is not automatable and is manually verified via the standalone probe. install compiles the helper, provisions the key, exports the pubkey, then deploys, with defined recovery on any step failure."
  }
]
```
