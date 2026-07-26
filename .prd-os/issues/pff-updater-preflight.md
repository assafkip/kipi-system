---
id: pff-updater-preflight
title: Wire the gate into kipi update fail-closed and version locked
status: closed
priority: p0
parent_prd: prd-prevent-fact-fanout-2026-07-25
allowed_files:
  - kipi-update.sh
  - q-system/.q-system/scripts/propagation-leak-gate.py
  - q-system/.q-system/scripts/test/test-kipi-update-leak-preflight.sh
  - q-system/.q-system/scripts/test/test-kipi-update-safety.sh
  - q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh
  - q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh
  - q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh
  - q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh
  - q-system/.q-system/scripts/test/test-updater-issue-sequence.py
disallowed_files:
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-leak-preflight.sh
required_reviews:
  - updater-owner
  - security
bypass_check: "bash q-system/.q-system/scripts/test/test-kipi-update-leak-preflight.sh --assert-no-silent-skip"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-prevent-fact-fanout-2026-07-25 finding=finding-6 at=2026-07-25T18:11:12Z -->

# Wire the gate into kipi update fail-closed and version locked

## Context

Parent PRD: `.prd-os/prds/prd-prevent-fact-fanout-2026-07-25.md`

## Acceptance

Write the failing no-instance-written reproducer first. A new leak aborts before any instance is read or written; a missing gate script or a classifier/scope version mismatch aborts rather than skipping.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Wire the gate into kipi update fail-closed and version locked
