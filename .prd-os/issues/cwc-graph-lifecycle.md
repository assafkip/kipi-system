---
id: cwc-graph-lifecycle
title: Define durable graph initialization, backup, and restore
status: open
priority: p1
parent_prd: prd-canonical-writeback-contract-2026-07-24
allowed_files:
  - q-system/.q-system/schemas/graph-record.schema.json
  - q-system/.q-system/scripts/graph-lifecycle.py
  - q-system/.q-system/tests/test_graph_lifecycle.py
disallowed_files:
  - q-system/memory/graph.jsonl
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_graph_lifecycle.py
required_reviews:
  - data-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_graph_lifecycle.py -k 'fresh_clone or corrupt_line or duplicate_import'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-writeback-contract-2026-07-24 finding=finding-4 at=2026-07-24T21:05:26Z -->

# Define durable graph initialization, backup, and restore

## Context

Parent PRD: `.prd-os/prds/prd-canonical-writeback-contract-2026-07-24.md`

## Acceptance

Write failing fresh-clone, corrupt-line, duplicate-import, backup-restore, and 10,000-record boot tests first. Compact before read, archive with receipts, initialize empty, append with provenance, and verify durable hashes.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Define durable graph initialization, backup, and restore
