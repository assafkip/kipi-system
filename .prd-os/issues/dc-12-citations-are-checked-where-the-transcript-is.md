---
id: dc-12-citations-are-checked-where-the-transcript-is
title: A hook verifies cited repo files were opened this session and seal requires that record
status: closed
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_citations.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_citations.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_citations.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-6 at=2026-09-18T20:21:26Z -->

# A hook verifies cited repo files were opened this session and seal requires that record

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

The PostToolUse branch on a write of craft-manifest.json or proof.md imports opened() from read-first-gate.py, checks every repo path in reference fields, and writes citations.json keyed to the manifest sha with the session id. No transcript means no record, never a pass. seal refuses when the record is missing or stale. Test feeds a fixture transcript.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] A hook verifies cited repo files were opened this session and seal requires that record
