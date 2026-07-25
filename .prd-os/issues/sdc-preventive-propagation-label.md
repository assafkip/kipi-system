---
id: sdc-preventive-propagation-label
title: Distinguish storage breach from preventive propagation proof
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/tests/separation/test_containment_claims.py
disallowed_files:
  - kipi-update.sh
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_claims.py
required_reviews:
  - updater-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_claims.py -k no_unproven_propagation"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-9 at=2026-07-24T20:50:23Z -->

# Distinguish storage breach from preventive propagation proof

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write a failing claim-classification test first. Assert that current canonical exposure is a storage breach and propagation remains preventive until final-state evidence exists.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Distinguish storage breach from preventive propagation proof
