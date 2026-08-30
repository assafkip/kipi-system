---
id: enforcement-lint-mutation-matrix
title: One enumerated mutation per blocking condition, each shown red before the tree is shown green
status: closed
priority: p0
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/.q-system/scripts/test_enforced_claim_lint.py
  - q-system/.q-system/scripts/test/enforced-claim-mutation-matrix.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/enforced-claim-mutation-matrix.sh
required_reviews: []
bypass_check: "the matrix derives its case list from the lint's own condition table rather than a hand-written list, and every condition has a case"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-14 at=2026-08-21T17:23:12Z -->

# One enumerated mutation per blocking condition, each shown red before the tree is shown green

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] One enumerated mutation per blocking condition, each shown red before the tree is shown green
