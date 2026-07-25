---
id: fcu-dry-run-final-state
title: Make dry run predict the exact final updater state
status: closed
priority: p0
parent_prd: prd-fail-closed-fleet-updater-2026-07-24
allowed_files:
  - kipi-update.sh
  - q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh
disallowed_files:
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
  - .git/**
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh
required_reviews:
  - updater-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh --assert-byte-equivalent"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-fail-closed-fleet-updater-2026-07-24 finding=finding-2 at=2026-07-24T20:57:37Z -->

# Make dry run predict the exact final updater state

## Context

Parent PRD: `.prd-os/prds/prd-fail-closed-fleet-updater-2026-07-24.md`

## Acceptance

Write the failing dry-versus-real equivalence test first. Model restore, settings merge, agents, rules, plugins, and final commit diff in a disposable fixture.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Make dry run predict the exact final updater state
