---
id: sdc-inventory-scope
title: Build the redacted instance-fact inventory
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/instance-fact-inventory.py
  - q-system/.q-system/tests/separation/test_instance_fact_inventory.py
disallowed_files:
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
  - .git/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_instance_fact_inventory.py
required_reviews:
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_instance_fact_inventory.py -k 'unknown_owner or raw_fact'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-1 at=2026-07-24T20:50:23Z -->

# Build the redacted instance-fact inventory

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write the failing inventory contract test first. Derive targets from tracked files, emit hashes and redacted identifiers only, and fail closed on unknown ownership.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Build the redacted instance-fact inventory
