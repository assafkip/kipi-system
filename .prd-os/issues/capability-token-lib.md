---
id: capability-token-lib
title: capability-token.sh: hash, atomic check-and-consume, mint, audit logging
status: in-progress
priority: p1
parent_prd: prd-capability-approval-token-2026-06-16
allowed_files:
  - plugins/kipi-core/scripts/capability-token.sh
  - plugins/kipi-core/scripts/test/test-capability-token.sh
disallowed_files: []
required_checks:
  - bash plugins/kipi-core/scripts/test/test-capability-token.sh
required_reviews: []
bypass_check: "bash plugins/kipi-core/scripts/test/test-capability-token.sh"
---
<!-- generated-by: prd_split.py prd=prd-capability-approval-token-2026-06-16 finding=finding-4 at=2026-06-16T03:29:23Z -->

# capability-token.sh: hash, atomic check-and-consume, mint, audit logging

## Context

Parent PRD: `.prd-os/prds/prd-capability-approval-token-2026-06-16.md`

## Acceptance

check denies with no token; mint then check allows exactly once; second check denied (consumed); expired token denied; malformed/unreadable expiry denied; full 64-hex hash is deterministic for identical command+cwd and differs for any change; concurrent double-consume is impossible (atomic rename); grant and consume each append one JSON line to the audit log.
