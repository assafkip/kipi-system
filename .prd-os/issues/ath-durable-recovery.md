---
id: ath-durable-recovery
title: Bound retries and distinguish durable recovery
status: open
priority: p1
parent_prd: prd-automation-terminal-health-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/launchd-health-check.py
  - q-system/.q-system/config/retry-tiers.json
  - q-system/.q-system/tests/test_durable_recovery.py
disallowed_files:
  - q-system/output/**
  - instance-registry.json
  - .prd-os/**
  - /Users/assafkipnis/projects/cole-gtm/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_durable_recovery.py
required_reviews:
  - automation-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_durable_recovery.py -k 'provisional or exhausted'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-automation-terminal-health-2026-07-24 finding=finding-3 at=2026-07-24T21:08:00Z -->

# Bound retries and distinguish durable recovery

## Context

Parent PRD: `.prd-os/prds/prd-automation-terminal-health-2026-07-24.md`

## Acceptance

Write failing retry-success-then-failure and exhausted-tier tests first. Require bounded attempts, a clear terminal state, and a later scheduled success before durable recovery.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Bound retries and distinguish durable recovery
