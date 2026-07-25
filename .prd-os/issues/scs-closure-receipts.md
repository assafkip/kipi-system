---
id: scs-closure-receipts
title: Require issue and closeout receipts for closure
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - plugins/prd-os/scripts/spillover_receipts.py
  - plugins/prd-os/tests/test_spillover_receipts.py
disallowed_files:
  - .prd-os/spillover.jsonl
  - .prd-os/receipts.jsonl
  - plugins/prd-os/scripts/prd_runner.py
  - q-system/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_receipts.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_receipts.py -k 'missing or mismatch or forged'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-3 at=2026-07-24T21:14:34Z -->

# Require issue and closeout receipts for closure

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write failing closed-frontmatter-without-receipt, mismatched-PRD, unknown-issue, and forged-receipt tests first. Require both closed issue state and a matching closeout record.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Require issue and closeout receipts for closure
