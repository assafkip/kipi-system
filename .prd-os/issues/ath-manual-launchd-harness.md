---
id: ath-manual-launchd-harness
title: Verify terminal delivery manually and under launchd
status: open
priority: p1
parent_prd: prd-automation-terminal-health-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/test-launchd-terminal-health.py
  - q-system/.q-system/tests/test_launchd_terminal_harness.py
disallowed_files:
  - q-system/output/**
  - instance-registry.json
  - .prd-os/**
  - /Users/assafkipnis/projects/cole-gtm/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_launchd_terminal_harness.py
required_reviews:
  - automation-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_launchd_terminal_harness.py -k 'environment_delta or teardown'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-automation-terminal-health-2026-07-24 finding=finding-4 at=2026-07-24T21:08:00Z -->

# Verify terminal delivery manually and under launchd

## Context

Parent PRD: `.prd-os/prds/prd-automation-terminal-health-2026-07-24.md`

## Acceptance

Write a failing manual-pass launchd-fail fixture first. Use unique temporary labels, validate equal receipt invariants, and assert teardown.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Verify terminal delivery manually and under launchd
