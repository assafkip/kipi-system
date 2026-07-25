---
id: sdc-updater-dependency-receipt
title: Require the updater final-state dependency receipt
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/tests/separation/test_updater_dependency_receipt.py
disallowed_files:
  - kipi-update.sh
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_updater_dependency_receipt.py
required_reviews:
  - updater-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_updater_dependency_receipt.py -k missing_or_open"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-13 at=2026-07-24T20:50:23Z -->

# Require the updater final-state dependency receipt

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write a failing missing-receipt test first. Block propagation proof until issue fcu-dry-run-final-state from prd-fail-closed-fleet-updater-2026-07-24 is closed with verification receipts.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Require the updater final-state dependency receipt
