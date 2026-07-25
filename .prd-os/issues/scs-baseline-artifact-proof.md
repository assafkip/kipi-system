---
id: scs-baseline-artifact-proof
title: Create the reviewed baseline artifact with event hashes
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - .prd-os/spillover-baseline.json
  - plugins/prd-os/tests/test_spillover_baseline_artifact.py
disallowed_files:
  - .prd-os/spillover.jsonl
  - .prd-os/gates.jsonl
  - plugins/prd-os/scripts/**
  - q-system/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_baseline_artifact.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_baseline_artifact.py -k changed_event"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-9 at=2026-07-24T21:14:34Z -->

# Create the reviewed baseline artifact with event hashes

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write failing missing-head and changed-effective-event tests first. Record reviewed IDs, ledger head hash, and effective event hashes so later changes are classified as new debt.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Create the reviewed baseline artifact with event hashes
