---
id: cwc-end-to-end-writeback
title: Prove debrief, calibration, morning, and MCP share write-back
status: open
priority: p1
parent_prd: prd-canonical-writeback-contract-2026-07-24
allowed_files:
  - q-system/.q-system/tests/test_canonical_writeback_e2e.py
  - plugins/kipi-core/kipi-mcp/tests/test_canonical_writeback_e2e.py
disallowed_files:
  - q-system/canonical/**
  - plugins/kipi-core/kipi-mcp/src/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_canonical_writeback_e2e.py plugins/kipi-core/kipi-mcp/tests/test_canonical_writeback_e2e.py
required_reviews:
  - runtime-owner
  - data-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_canonical_writeback_e2e.py -k two_brain"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-writeback-contract-2026-07-24 finding=finding-5 at=2026-07-24T21:05:26Z -->

# Prove debrief, calibration, morning, and MCP share write-back

## Context

Parent PRD: `.prd-os/prds/prd-canonical-writeback-contract-2026-07-24.md`

## Acceptance

Write the failing two-reader fixture first. Treat this as proof-only and wait for cwc-writeback-ownership plus srsa-unified-readers to close. Write one synthetic record through debrief and calibration and prove morning and MCP read the same hash, freshness, and provenance.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Prove debrief, calibration, morning, and MCP share write-back
