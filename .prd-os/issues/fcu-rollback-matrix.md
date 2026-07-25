---
id: fcu-rollback-matrix
title: Prove rollback across updater failure phases
status: closed
priority: p0
parent_prd: prd-fail-closed-fleet-updater-2026-07-24
allowed_files:
  - kipi-rollback.sh
  - q-system/.q-system/scripts/test/test-kipi-rollback-matrix.sh
disallowed_files:
  - kipi-update.sh
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-rollback-matrix.sh
required_reviews:
  - updater-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-kipi-rollback-matrix.sh --assert-later-edit-refusal"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-fail-closed-fleet-updater-2026-07-24 finding=finding-5 at=2026-07-24T20:57:37Z -->

# Prove rollback across updater failure phases

## Context

Parent PRD: `.prd-os/prds/prd-fail-closed-fleet-updater-2026-07-24.md`

## Acceptance

Write failing phase-injection tests first. Restore only receipt-listed updater changes and refuse rollback over later user edits.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Prove rollback across updater failure phases
