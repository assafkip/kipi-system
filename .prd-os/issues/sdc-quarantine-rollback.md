---
id: sdc-quarantine-rollback
title: Keep rollback payloads out of generic paths
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/verify-containment-export.py
  - q-system/.q-system/tests/separation/test_containment_rollback.py
disallowed_files:
  - q-system/canonical/**
  - q-system/output/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_rollback.py
required_reviews:
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_rollback.py -k never_republish"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-12 at=2026-07-24T20:50:23Z -->

# Keep rollback payloads out of generic paths

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write a failing wrong-owner rollback reproducer first. Retain raw payloads only in protected quarantine or the verified owner and never restore them into generic files.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Keep rollback payloads out of generic paths
