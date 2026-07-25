---
id: cwc-graph-compaction-bound
title: Bound graph boot reads with receipt-backed compaction
status: open
priority: p1
parent_prd: prd-canonical-writeback-contract-2026-07-24
allowed_files:
  - q-system/.q-system/tests/test_graph_compaction_bound.py
disallowed_files:
  - q-system/.q-system/scripts/graph-lifecycle.py
  - q-system/memory/**
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_graph_compaction_bound.py
required_reviews:
  - data-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_graph_compaction_bound.py -k boot_bound"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-writeback-contract-2026-07-24 finding=finding-8 at=2026-07-24T21:05:26Z -->

# Bound graph boot reads with receipt-backed compaction

## Context

Parent PRD: `.prd-os/prds/prd-canonical-writeback-contract-2026-07-24.md`

## Acceptance

Write a failing 10,001-record boot test first. Require compaction before whole-file consumption, verified archive counts and hashes, and a bounded active-file read.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Bound graph boot reads with receipt-backed compaction
