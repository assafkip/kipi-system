---
id: scs-spillover-regression-matrix
title: Lock duplicate, stale, reference, and severity regressions
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - plugins/prd-os/tests/test_spillover_regressions.py
disallowed_files:
  - .prd-os/spillover.jsonl
  - plugins/prd-os/scripts/**
  - q-system/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_regressions.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_regressions.py -k 'duplicate or stale or invalid_reference or severity'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-6 at=2026-07-24T21:14:34Z -->

# Lock duplicate, stale, reference, and severity regressions

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write the failing regression fixtures first. Cover duplicate IDs, stale status, invalid resolution references, severity changes, and all three RCA event shapes.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Lock duplicate, stale, reference, and severity regressions
