---
id: fcu-shared-receipt-schema
title: Create one versioned updater and rollback receipt schema
status: closed
priority: p0
parent_prd: prd-fail-closed-fleet-updater-2026-07-24
allowed_files:
  - q-system/.q-system/schemas/updater-receipt.schema.json
  - q-system/.q-system/scripts/test/test-updater-receipt-contract.py
disallowed_files:
  - kipi-update.sh
  - kipi-rollback.sh
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 q-system/.q-system/scripts/test/test-updater-receipt-contract.py
required_reviews:
  - updater-owner
bypass_check: "python3 q-system/.q-system/scripts/test/test-updater-receipt-contract.py --producer-consumer-mismatch"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-fail-closed-fleet-updater-2026-07-24 finding=finding-8 at=2026-07-24T20:57:37Z -->

# Create one versioned updater and rollback receipt schema

## Context

Parent PRD: `.prd-os/prds/prd-fail-closed-fleet-updater-2026-07-24.md`

## Acceptance

Write failing producer-consumer compatibility tests first. Lock path, hash, phase, mode, schema-version, and rollback fields and reject unknown versions.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Create one versioned updater and rollback receipt schema
