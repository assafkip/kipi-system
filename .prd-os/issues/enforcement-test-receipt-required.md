---
id: enforcement-test-receipt-required
title: ENFORCED requires a named existing test file; exit-posture claim narrowed to what is decidable
status: open
priority: p0
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/.q-system/scripts/enforced-claim-lint.py
  - q-system/.q-system/scripts/test_enforced_claim_lint.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k posture
required_reviews: []
bypass_check: "the lint never executes a named enforcer: grep -E 'subprocess|os.system|popen' q-system/.q-system/scripts/enforced-claim-lint.py | grep -v '^[[:space:]]*#' | wc -l | grep -qx 0"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-5 at=2026-08-21T17:23:12Z -->

# ENFORCED requires a named existing test file; exit-posture claim narrowed to what is decidable

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] ENFORCED requires a named existing test file; exit-posture claim narrowed to what is decidable
