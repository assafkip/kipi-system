---
id: sdc-versioned-baseline-receipt
title: Store a reproducible separation baseline receipt
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/tests/separation/fixtures/validate-separation-baseline.txt
  - q-system/.q-system/tests/separation/test_baseline_receipt.py
disallowed_files:
  - validate-separation.py
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_baseline_receipt.py
required_reviews:
  - test-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_baseline_receipt.py -k stale_or_unattributed"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-14 at=2026-07-24T20:50:23Z -->

# Store a reproducible separation baseline receipt

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write a failing stale-receipt test first. Record the command, commit SHA, timestamp, exit code, and exact summary without attributing failures not present in the receipt.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Store a reproducible separation baseline receipt
