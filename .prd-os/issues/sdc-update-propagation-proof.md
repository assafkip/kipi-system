---
id: sdc-update-propagation-proof
title: Prove updater final states reject injected instance facts
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/tests/separation/test_update_propagation.py
disallowed_files:
  - kipi-update.sh
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_update_propagation.py
required_reviews:
  - updater-owner
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_update_propagation.py -k 'final_state and injected_fact'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-3 at=2026-07-24T20:50:23Z -->

# Prove updater final states reject injected instance facts

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write the failing final-state reproducer first. Do not start until fcu-dry-run-final-state is closed. Test registered layout fixtures without changing production instances.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Prove updater final states reject injected instance facts
