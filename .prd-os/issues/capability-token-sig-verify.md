---
id: capability-token-sig-verify
title: capability-token.sh: domain-separated signed token, verify-before-allow, no-downgrade
status: in-progress
priority: p1
parent_prd: prd-capability-token-signing-2026-06-16
allowed_files:
  - plugins/kipi-core/scripts/capability-token.sh
  - plugins/kipi-core/scripts/test/test-capability-token-sig.sh
  - plugins/kipi-core/scripts/test/test-capability-token.sh
disallowed_files: []
required_checks:
  - bash plugins/kipi-core/scripts/test/test-capability-token-sig.sh
  - bash plugins/kipi-core/scripts/test/test-capability-token.sh
required_reviews: []
bypass_check: "bash plugins/kipi-core/scripts/test/test-capability-token-sig.sh"
---
<!-- generated-by: prd_split.py prd=prd-capability-token-signing-2026-06-16 finding=finding-2 at=2026-06-16T05:02:47Z -->

# capability-token.sh: domain-separated signed token, verify-before-allow, no-downgrade

## Context

Parent PRD: `.prd-os/prds/prd-capability-token-signing-2026-06-16.md`

## Acceptance

Token payload is the domain-separated, versioned string capability-token.v1 + LF + hash + LF + expiry. mint signs it; check atomically claims then verifies the ECDSA P-256/SHA-256 DER signature against the trusted public key BEFORE allowing. Negative cases all deny (fail closed, no downgrade): forged/unsigned token, wrong/swapped pubkey, missing pubkey, expired signed token, malformed token, replay after consume. Positive: a validly signed unexpired token is allowed exactly once then consumed. Tests use a software EC-key signer backend (no Touch ID).
