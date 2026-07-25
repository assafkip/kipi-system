---
id: srsa-complete-record-class-mapping
title: Verify every current KipiPaths record class migrates
status: open
priority: p0
parent_prd: prd-single-runtime-state-authority-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/tests/test_record_class_migration.py
disallowed_files:
  - plugins/kipi-core/kipi-mcp/src/**
  - q-system/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_record_class_migration.py
required_reviews:
  - data-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_record_class_migration.py -k unmapped_class"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-single-runtime-state-authority-2026-07-24 finding=finding-7 at=2026-07-24T20:54:11Z -->

# Verify every current KipiPaths record class migrates

## Context

Parent PRD: `.prd-os/prds/prd-single-runtime-state-authority-2026-07-24.md`

## Acceptance

Write a failing enumeration test first. Introspect every KipiPaths writable record class and require a destination mapping, copied hash, and verification receipt.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Verify every current KipiPaths record class migrates
