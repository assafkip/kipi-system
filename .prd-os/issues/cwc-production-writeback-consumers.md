---
id: cwc-production-writeback-consumers
title: Prove every write-back mapping has production consumers
status: open
priority: p1
parent_prd: prd-canonical-writeback-contract-2026-07-24
allowed_files:
  - q-system/.q-system/tests/test_writeback_production_consumers.py
disallowed_files:
  - q-system/.q-system/scripts/**
  - q-system/canonical/**
  - plugins/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_writeback_production_consumers.py
required_reviews:
  - data-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_writeback_production_consumers.py -k dead_mapping"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-writeback-contract-2026-07-24 finding=finding-6 at=2026-07-24T21:05:26Z -->

# Prove every write-back mapping has production consumers

## Context

Parent PRD: `.prd-os/prds/prd-canonical-writeback-contract-2026-07-24.md`

## Acceptance

Write a failing dead-mapping test first. Introspect every configured write-back class and require a non-test production reader and writer.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Prove every write-back mapping has production consumers
