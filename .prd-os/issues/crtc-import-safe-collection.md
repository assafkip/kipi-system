---
id: crtc-import-safe-collection
title: Make script test modules import-safe
status: open
priority: p1
parent_prd: prd-complete-repo-test-contract-2026-07-24
allowed_files:
  - scripts/test_persona_reorg.py
  - tests/test_collection_contract.py
disallowed_files:
  - .github/workflows/**
  - plugins/**
  - q-system/**
  - .prd-os/**
required_checks:
  - python3 -m pytest --collect-only -q scripts/test_persona_reorg.py
  - python3 -m pytest -q tests/test_collection_contract.py
required_reviews:
  - test-owner
bypass_check: "python3 -m pytest -q tests/test_collection_contract.py -k sys_exit"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-complete-repo-test-contract-2026-07-24 finding=finding-4 at=2026-07-24T21:01:37Z -->

# Make script test modules import-safe

## Context

Parent PRD: `.prd-os/prds/prd-complete-repo-test-contract-2026-07-24.md`

## Acceptance

Write the failing targeted collection reproducer first. Move execution behind explicit entrypoints and prove importing scripts/test_persona_reorg.py cannot terminate the process.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Make script test modules import-safe
