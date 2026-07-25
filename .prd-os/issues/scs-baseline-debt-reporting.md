---
id: scs-baseline-debt-reporting
title: Separate pre-existing and new debt in gates run
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - plugins/prd-os/scripts/prd_runner.py
  - plugins/prd-os/schemas/spillover-baseline.schema.json
  - plugins/prd-os/tests/test_spillover_baseline.py
  - .prd-os/spillover-baseline.json
disallowed_files:
  - .prd-os/spillover.jsonl
  - .prd-os/gates.jsonl
  - q-system/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_baseline.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_baseline.py -k 'reopen or severity or invalid_head'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-5 at=2026-07-24T21:14:34Z -->

# Separate pre-existing and new debt in gates run

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write failing baseline-reopen, severity-increase, new-ID, and invalid-head-hash tests first. Print old and new debt separately and return nonzero only for new debt, invalid ledger state, or red registered gates.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Separate pre-existing and new debt in gates run
