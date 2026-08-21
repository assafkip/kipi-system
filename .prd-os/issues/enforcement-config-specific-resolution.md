---
id: enforcement-config-specific-resolution
title: Resolve the exec against the NAMED config, not any config
status: closed
priority: p0
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/.q-system/scripts/enforced-claim-lint.py
  - q-system/.q-system/scripts/test_enforced_claim_lint.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k named_config
required_reviews: []
bypass_check: "a wrong config value fails even when another config references the exec: the named_config mutation exits 2"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-8 at=2026-08-21T17:23:12Z -->

# Resolve the exec against the NAMED config, not any config

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Resolve the exec against the NAMED config, not any config
