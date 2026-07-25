---
id: cwc-proof-only-dependency-gate
title: Block end-to-end proof until production wiring closes
status: open
priority: p1
parent_prd: prd-canonical-writeback-contract-2026-07-24
allowed_files:
  - q-system/.q-system/tests/test_writeback_dependency_gate.py
disallowed_files:
  - q-system/.q-system/scripts/**
  - plugins/**/src/**
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_writeback_dependency_gate.py
required_reviews:
  - runtime-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_writeback_dependency_gate.py -k missing_receipt"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-writeback-contract-2026-07-24 finding=finding-7 at=2026-07-24T21:05:26Z -->

# Block end-to-end proof until production wiring closes

## Context

Parent PRD: `.prd-os/prds/prd-canonical-writeback-contract-2026-07-24.md`

## Acceptance

Write a failing missing-receipt test first. Refuse end-to-end proof until cwc-writeback-ownership and srsa-unified-readers are closed with verification receipts.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Block end-to-end proof until production wiring closes
