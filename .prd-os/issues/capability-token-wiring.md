---
id: capability-token-wiring
title: kipi-approve wrapper, idempotent install, and hook integration verified against a copy
status: in-progress
priority: p1
parent_prd: prd-capability-approval-token-2026-06-16
allowed_files:
  - plugins/kipi-core/scripts/kipi-approve
  - plugins/kipi-core/scripts/install-capability-token.sh
  - plugins/kipi-core/scripts/test/test-capability-token-wiring.sh
disallowed_files: []
required_checks:
  - bash plugins/kipi-core/scripts/test/test-capability-token-wiring.sh
required_reviews: []
bypass_check: "bash plugins/kipi-core/scripts/test/test-capability-token-wiring.sh"
---
<!-- generated-by: prd_split.py prd=prd-capability-approval-token-2026-06-16 finding=finding-14 at=2026-06-16T03:29:23Z -->

# kipi-approve wrapper, idempotent install, and hook integration verified against a copy

## Context

Parent PRD: `.prd-os/prds/prd-capability-approval-token-2026-06-16.md`

## Acceptance

install is idempotent and sets 0755 on scripts and 0700 on the approvals dir; kipi-approve <hash> mints a valid token; the wiring test copies the real destructive-op-deny.sh into a temp HOME, applies the integration, and proves end-to-end: a destructive command is denied with no token, denied when the script is absent (fail closed), and allowed exactly once after kipi-approve, then denied again.
