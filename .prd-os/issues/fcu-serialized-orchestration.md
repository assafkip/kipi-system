---
id: fcu-serialized-orchestration
title: Enforce updater implementation order for shared orchestration
status: closed
priority: p0
parent_prd: prd-fail-closed-fleet-updater-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/test/test-updater-issue-sequence.py
disallowed_files:
  - kipi-update.sh
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 q-system/.q-system/scripts/test/test-updater-issue-sequence.py
required_reviews:
  - updater-owner
bypass_check: "python3 q-system/.q-system/scripts/test/test-updater-issue-sequence.py --reject-out-of-order"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-fail-closed-fleet-updater-2026-07-24 finding=finding-7 at=2026-07-24T20:57:37Z -->

# Enforce updater implementation order for shared orchestration

## Context

Parent PRD: `.prd-os/prds/prd-fail-closed-fleet-updater-2026-07-24.md`

## Acceptance

Write the failing out-of-order test first. Require preservation precondition, then final-state dry run, then hook-safe commits, with all prior checks rerun at each step.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Enforce updater implementation order for shared orchestration
