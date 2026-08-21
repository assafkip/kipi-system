---
id: enforcement-advisory-under-marker-blocked
title: ADVISORY under a live ENFORCED marker requires an open spillover ref; disposition pass over the 14 files
status: open
priority: p0
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/.q-system/scripts/enforced-claim-lint.py
  - q-system/.q-system/scripts/test_enforced_claim_lint.py
  - q-system/.q-system/proposals/*.json
  - q-system/.q-system/enforced-claim-baseline.json
  - q-system/.q-system/scripts/instruction-budget-audit.py
  - q-system/.q-system/scripts/test_instruction_budget_audit.py
  - q-system/.q-system/capability-manifest.json
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k advisory
  - python3 q-system/.q-system/scripts/enforced-claim-lint.py --all
required_reviews: []
bypass_check: "no ADVISORY entry can pass under a live marker without a resolving ref: the advisory mutation case exits 2"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-4 at=2026-08-21T17:23:12Z -->

# ADVISORY under a live ENFORCED marker requires an open spillover ref; disposition pass over the 14 files

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] ADVISORY under a live ENFORCED marker requires an open spillover ref; disposition pass over the 14 files
