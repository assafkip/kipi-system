---
id: cwc-canonical-consumer-inventory
title: Inventory canonical readers and remove or generate eight duplicates
status: open
priority: p1
parent_prd: prd-canonical-writeback-contract-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/canonical/**
  - plugins/kipi-core/kipi-mcp/tests/test_canonical_authority.py
disallowed_files:
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_canonical_authority.py
required_reviews:
  - runtime-owner
  - data-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_canonical_authority.py -k manual_drift"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-writeback-contract-2026-07-24 finding=finding-1 at=2026-07-24T21:05:26Z -->

# Inventory canonical readers and remove or generate eight duplicates

## Context

Parent PRD: `.prd-os/prds/prd-canonical-writeback-contract-2026-07-24.md`

## Acceptance

Write a failing duplicate-authority test first. Wait for the state-authority receipt, enumerate consumers, and remove copies or generate them with source hashes and semantic agreement.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Inventory canonical readers and remove or generate eight duplicates
