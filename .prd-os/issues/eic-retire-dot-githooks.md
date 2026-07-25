---
id: eic-retire-dot-githooks
title: Retire the competing tracked githooks path after parity
status: open
priority: p1
parent_prd: prd-enforcement-instruction-contract-2026-07-24
allowed_files:
  - .githooks/pre-commit
  - .githooks/pre-push
  - tests/test_single_hook_authority.py
disallowed_files:
  - lefthook.yml
  - .git/hooks/**
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_single_hook_authority.py
required_reviews:
  - enforcement-owner
bypass_check: "python3 -m pytest -q tests/test_single_hook_authority.py -k no_second_authority"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforcement-instruction-contract-2026-07-24 finding=finding-8 at=2026-07-24T21:10:19Z -->

# Retire the competing tracked githooks path after parity

## Context

Parent PRD: `.prd-os/prds/prd-enforcement-instruction-contract-2026-07-24.md`

## Acceptance

Write a failing dual-authority test first. Require Lefthook behavior parity and documentation agreement before deleting tracked hook files, then prove no active or documented second path remains.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Retire the competing tracked githooks path after parity
