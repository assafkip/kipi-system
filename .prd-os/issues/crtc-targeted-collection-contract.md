---
id: crtc-targeted-collection-contract
title: Keep the import-safe issue independently collectable
status: open
priority: p1
parent_prd: prd-complete-repo-test-contract-2026-07-24
allowed_files:
  - tests/test_targeted_collection.py
disallowed_files:
  - scripts/test_persona_reorg.py
  - plugins/**
  - .github/workflows/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_targeted_collection.py
required_reviews:
  - test-owner
bypass_check: "python3 -m pytest -q tests/test_targeted_collection.py -k no_cross_suite_dependency"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-complete-repo-test-contract-2026-07-24 finding=finding-8 at=2026-07-24T21:01:37Z -->

# Keep the import-safe issue independently collectable

## Context

Parent PRD: `.prd-os/prds/prd-complete-repo-test-contract-2026-07-24.md`

## Acceptance

Write a failing isolated-collection fixture first. Collect only scripts/test_persona_reorg.py in an environment that does not require MCP or design dependencies.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Keep the import-safe issue independently collectable
