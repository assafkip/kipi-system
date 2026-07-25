---
id: sdc-serial-execution-contract
title: Lock containment issue execution order
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/tests/separation/test_containment_sequence.py
disallowed_files:
  - validate-separation.py
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_sequence.py
required_reviews:
  - test-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_sequence.py -k refuses_out_of_order"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-8 at=2026-07-24T20:50:23Z -->

# Lock containment issue execution order

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write a failing ordering test first. Require inventory and quarantine before export, export receipt before template restoration, and updater final-state receipt before propagation proof.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Lock containment issue execution order
