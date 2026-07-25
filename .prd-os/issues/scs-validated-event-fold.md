---
id: scs-validated-event-fold
title: Implement the validated latest-event fold
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - plugins/prd-os/scripts/spillover_events.py
  - plugins/prd-os/schemas/spillover-event.schema.json
  - plugins/prd-os/tests/test_spillover_events.py
disallowed_files:
  - .prd-os/spillover.jsonl
  - plugins/prd-os/scripts/prd_runner.py
  - q-system/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py -k 'invalid or duplicate or timestamp'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-1 at=2026-07-24T21:14:34Z -->

# Implement the validated latest-event fold

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write failing invalid-JSON, invalid-transition, duplicate-ID, and out-of-order-timestamp tests first. Fold valid events by file order and fail closed with line evidence.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Implement the validated latest-event fold
