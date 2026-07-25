---
id: sdc-semantic-classifier
title: Add deterministic semantic leakage classification
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - validate-separation.py
  - q-system/.q-system/tests/separation/test_semantic_client_leakage.py
disallowed_files:
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
  - .git/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py
required_reviews:
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py -k 'unknown_name and unclassified'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-2 at=2026-07-24T20:50:23Z -->

# Add deterministic semantic leakage classification

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write the failing synthetic fixture first. Detect populated fact fields, currency, sourced interactions, and case proof gaps while allowing placeholders and explicitly synthetic fixtures.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Add deterministic semantic leakage classification
