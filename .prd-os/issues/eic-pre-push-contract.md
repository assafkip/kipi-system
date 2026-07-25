---
id: eic-pre-push-contract
title: Restore the pre-push enforcement contract in Lefthook
status: open
priority: p1
parent_prd: prd-enforcement-instruction-contract-2026-07-24
allowed_files:
  - lefthook.yml
  - tests/test_pre_push_contract.py
disallowed_files:
  - .git/hooks/**
  - .githooks/**
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_pre_push_contract.py
required_reviews:
  - enforcement-owner
bypass_check: "python3 -m pytest -q tests/test_pre_push_contract.py -k documented_active_parity"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforcement-instruction-contract-2026-07-24 finding=finding-2 at=2026-07-24T21:10:19Z -->

# Restore the pre-push enforcement contract in Lefthook

## Context

Parent PRD: `.prd-os/prds/prd-enforcement-instruction-contract-2026-07-24.md`

## Acceptance

Write a failing missing-pre-push test first. Port every still-valid tracked pre-push proof or document and test an equivalent executable replacement.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Restore the pre-push enforcement contract in Lefthook
