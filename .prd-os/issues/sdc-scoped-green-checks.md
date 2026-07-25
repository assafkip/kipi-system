---
id: sdc-scoped-green-checks
title: Use scoped green checks for containment issues
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/tests/separation/test_containment_scoped_checks.py
disallowed_files:
  - validate-separation.py
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_scoped_checks.py
required_reviews:
  - test-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_scoped_checks.py -k unrelated_failure"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-5 at=2026-07-24T20:50:23Z -->

# Use scoped green checks for containment issues

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write a failing test that proves containment checks do not inherit unrelated baseline failures, then require each scoped command to exit zero.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Use scoped green checks for containment issues
