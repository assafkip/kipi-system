---
id: ath-watchdog-exit-modes
title: Separate watchdog gate status from notification delivery
status: open
priority: p1
parent_prd: prd-automation-terminal-health-2026-07-24
allowed_files:
  - q-system/.q-system/tests/test_launchd_health_exit_modes.py
disallowed_files:
  - q-system/.q-system/scripts/launchd-health-check.py
  - q-system/output/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_launchd_health_exit_modes.py
required_reviews:
  - automation-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_launchd_health_exit_modes.py -k failed_job_never_green"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-automation-terminal-health-2026-07-24 finding=finding-8 at=2026-07-24T21:08:00Z -->

# Separate watchdog gate status from notification delivery

## Context

Parent PRD: `.prd-os/prds/prd-automation-terminal-health-2026-07-24.md`

## Acceptance

Write a failing red-gate-zero-exit test first. Require gate mode to exit nonzero on failed terminal invariants and report notification success as a separate field.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Separate watchdog gate status from notification delivery
