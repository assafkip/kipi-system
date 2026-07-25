---
id: scs-concurrent-append-lock
title: Make spillover validation and append atomic
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - plugins/prd-os/scripts/spillover_lock.py
  - plugins/prd-os/tests/test_spillover_concurrency.py
disallowed_files:
  - .prd-os/spillover.jsonl
  - plugins/prd-os/scripts/prd_runner.py
  - q-system/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_concurrency.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_concurrency.py -k n_process"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-7 at=2026-07-24T21:14:34Z -->

# Make spillover validation and append atomic

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write a failing N-process append reproducer first. Hold one stable lock across prior-event validation and append, preserve line integrity, and reject stale prior hashes.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Make spillover validation and append atomic
