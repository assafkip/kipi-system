---
id: cwc-writeback-ownership
title: Route every canonical write-back class to one owner
status: open
priority: p1
parent_prd: prd-canonical-writeback-contract-2026-07-24
allowed_files:
  - q-system/.q-system/config/canonical-writeback.json
  - q-system/.q-system/scripts/canonical-writeback.py
  - q-system/.q-system/scripts/changelog-write.py
  - q-system/.q-system/scripts/canonical-digest.py
  - q-system/.q-system/tests/test_canonical_writeback.py
disallowed_files:
  - q-system/canonical/**
  - plugins/kipi-core/kipi-mcp/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_canonical_writeback.py
required_reviews:
  - data-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_canonical_writeback.py -k unmapped_writer"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-writeback-contract-2026-07-24 finding=finding-2 at=2026-07-24T21:05:26Z -->

# Route every canonical write-back class to one owner

## Context

Parent PRD: `.prd-os/prds/prd-canonical-writeback-contract-2026-07-24.md`

## Acceptance

Write a failing unmapped-writer test first. Cover changelog, decisions, market intelligence, content intelligence, and objections with one authority and owner each, and prove every mapping has a production reader and writer.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Route every canonical write-back class to one owner
