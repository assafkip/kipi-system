---
id: eic-hook-issue-order
title: Enforce pre-push, retirement, then installer order
status: open
priority: p1
parent_prd: prd-enforcement-instruction-contract-2026-07-24
allowed_files:
  - tests/test_hook_issue_order.py
disallowed_files:
  - lefthook.yml
  - .githooks/**
  - .git/hooks/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_hook_issue_order.py
required_reviews:
  - enforcement-owner
bypass_check: "python3 -m pytest -q tests/test_hook_issue_order.py -k refuses_out_of_order"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforcement-instruction-contract-2026-07-24 finding=finding-9 at=2026-07-24T21:10:19Z -->

# Enforce pre-push, retirement, then installer order

## Context

Parent PRD: `.prd-os/prds/prd-enforcement-instruction-contract-2026-07-24.md`

## Acceptance

Write a failing out-of-order test first. Require pre-push parity before githooks retirement and both receipts before fresh-clone installer verification.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Enforce pre-push, retirement, then installer order
