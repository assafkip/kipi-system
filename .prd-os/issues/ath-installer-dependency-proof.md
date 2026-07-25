---
id: ath-installer-dependency-proof
title: Verify dependencies before registration and after environment change
status: open
priority: p1
parent_prd: prd-automation-terminal-health-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/launchd-dependency-check.py
  - q-system/.q-system/tests/test_launchd_dependency_check.py
disallowed_files:
  - q-system/output/**
  - instance-registry.json
  - .prd-os/**
  - /Users/assafkipnis/projects/cole-gtm/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_launchd_dependency_check.py
required_reviews:
  - automation-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_launchd_dependency_check.py -k 'browser or executable or environment'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-automation-terminal-health-2026-07-24 finding=finding-2 at=2026-07-24T21:08:00Z -->

# Verify dependencies before registration and after environment change

## Context

Parent PRD: `.prd-os/prds/prd-automation-terminal-health-2026-07-24.md`

## Acceptance

Write failing missing-browser, missing-executable, and launchd-environment tests first. Block registration and emit a dependency snapshot on failure.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Verify dependencies before registration and after environment change
