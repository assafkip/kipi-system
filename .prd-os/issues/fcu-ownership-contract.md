---
id: fcu-ownership-contract
title: Define and enumerate instance-owned paths before mutation
status: closed
priority: p0
parent_prd: prd-fail-closed-fleet-updater-2026-07-24
allowed_files:
  - q-system/.q-system/config/instance-ownership-contract.json
  - q-system/.q-system/scripts/test/test-instance-ownership-contract.py
disallowed_files:
  - kipi-update.sh
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 q-system/.q-system/scripts/test/test-instance-ownership-contract.py
required_reviews:
  - updater-owner
bypass_check: "python3 q-system/.q-system/scripts/test/test-instance-ownership-contract.py --unclassified-must-fail"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-fail-closed-fleet-updater-2026-07-24 finding=finding-6 at=2026-07-24T20:57:37Z -->

# Define and enumerate instance-owned paths before mutation

## Context

Parent PRD: `.prd-os/prds/prd-fail-closed-fleet-updater-2026-07-24.md`

## Acceptance

Write failing unclassified-path and new-destination tests first. Enumerate every managed destination and classify preserved state, instance automation, and generic managed paths from the contract plus registry.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Define and enumerate instance-owned paths before mutation
