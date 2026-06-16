---
id: capability-signer-se
title: capability-signer Swift Secure-Enclave helper + install provisioning
status: open
priority: p1
parent_prd: prd-capability-token-signing-2026-06-16
allowed_files:
  - plugins/kipi-core/scripts/capability-signer.swift
  - plugins/kipi-core/scripts/install-capability-token.sh
  - plugins/kipi-core/scripts/test/test-capability-signer.sh
disallowed_files: []
required_checks:
  - bash plugins/kipi-core/scripts/test/test-capability-signer.sh
required_reviews: []
bypass_check: "bash plugins/kipi-core/scripts/test/test-capability-signer.sh"
---
<!-- generated-by: prd_split.py prd=prd-capability-token-signing-2026-06-16 finding=finding-4 at=2026-06-16T05:02:47Z -->

# capability-signer Swift Secure-Enclave helper + install provisioning

## Context

Parent PRD: `.prd-os/prds/prd-capability-token-signing-2026-06-16.md`

## Acceptance

capability-signer.swift compiles with swiftc. init creates a persistent SE P-256 key (ThisDeviceOnly, biometryCurrentSet, stable tag com.kipi.capability-token), idempotent (no duplicate keys), exports the public key as PEM. sign signs stdin bytes. The test proves swiftc compiles the helper and that an openssl-produced P-256/SHA-256 DER signature verifies with the exported-format public key (encoding compatibility), since the Touch-ID SE signing path is not automatable and is manually verified via the standalone probe. install compiles the helper, provisions the key, exports the pubkey, then deploys, with defined recovery on any step failure.
