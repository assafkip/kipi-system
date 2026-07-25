---
id: scs-verified-fold-checkpoint
title: Bound spillover reads with a verified fold checkpoint
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - plugins/prd-os/schemas/spillover-checkpoint.schema.json
  - plugins/prd-os/scripts/spillover_checkpoint.py
  - plugins/prd-os/tests/test_spillover_checkpoint.py
disallowed_files:
  - .prd-os/spillover.jsonl
  - plugins/prd-os/scripts/prd_runner.py
  - q-system/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_checkpoint.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_checkpoint.py -k 'boot_bound or stale or bad_hash'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-8 at=2026-07-24T21:14:34Z -->

# Bound spillover reads with a verified fold checkpoint

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write failing 10,001-event boot, stale-offset, and bad-head-hash tests first. Checkpoint before whole-file consumption and rebuild from JSONL on mismatch.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Bound spillover reads with a verified fold checkpoint
