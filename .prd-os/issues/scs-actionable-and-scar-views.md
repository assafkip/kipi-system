---
id: scs-actionable-and-scar-views
title: Separate actionable current work from historical scars
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - plugins/prd-os/scripts/spillover_views.py
  - plugins/prd-os/tests/test_spillover_views.py
disallowed_files:
  - .prd-os/spillover.jsonl
  - plugins/prd-os/scripts/prd_runner.py
  - q-system/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_views.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_views.py -k 'closed_in_open or missing_link or history'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-4 at=2026-07-24T21:14:34Z -->

# Separate actionable current work from historical scars

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write failing closed-in-open, superseded-without-link, and history-loss tests first. Derive actionable, scars, and full-history views from one fold.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Separate actionable current work from historical scars
