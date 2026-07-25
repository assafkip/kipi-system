---
id: sdc-redacted-inventory-boundary
title: Enforce the inventory redaction boundary
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/schemas/containment-inventory.schema.json
  - q-system/.q-system/scripts/instance-fact-inventory.py
  - q-system/.q-system/tests/separation/test_inventory_redaction.py
disallowed_files:
  - q-system/canonical/**
  - q-system/output/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_inventory_redaction.py
required_reviews:
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_inventory_redaction.py -k raw_payload"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-7 at=2026-07-24T20:50:23Z -->

# Enforce the inventory redaction boundary

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write the failing raw-fact persistence test first. Permit hashes, coordinates, fact classes, and redacted identifiers only in committed skeleton artifacts.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Enforce the inventory redaction boundary

## Amendments

### 2026-07-24T22:36:55Z
Reason: Codex found the passive schema did not enforce the boundary; include the inventory producer so every emitted artifact is validated before serialization

Before:
- allowed_files: ['q-system/.q-system/schemas/containment-inventory.schema.json', 'q-system/.q-system/tests/separation/test_inventory_redaction.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/separation/test_inventory_redaction.py']
- disallowed_files: ['q-system/canonical/**', 'q-system/output/**', 'instance-registry.json', '.prd-os/**']

After:
- allowed_files: ['q-system/.q-system/schemas/containment-inventory.schema.json', 'q-system/.q-system/scripts/instance-fact-inventory.py', 'q-system/.q-system/tests/separation/test_inventory_redaction.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/separation/test_inventory_redaction.py']
- disallowed_files: ['q-system/canonical/**', 'q-system/output/**', 'instance-registry.json', '.prd-os/**']
