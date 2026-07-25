---
id: scs-lifecycle-events
title: Append closure, supersession, void, and severity events
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - plugins/prd-os/scripts/prd_runner.py
  - plugins/prd-os/tests/test_spillover_lifecycle.py
disallowed_files:
  - .prd-os/spillover.jsonl
  - plugins/prd-os/schemas/**
  - q-system/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_lifecycle.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_lifecycle.py -k 'stale or severity or mutate'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-2 at=2026-07-24T21:14:34Z -->

# Append closure, supersession, void, and severity events

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write failing stale-status, severity-change, invalid-supersession, and history-mutation tests first. Express every correction as a new event.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Append closure, supersession, void, and severity events
