---
id: sdc-public-history-decision
title: Record public-history handling without rewriting history
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - ARCHITECTURE.md
  - q-system/.q-system/tests/separation/test_public_history_contract.py
disallowed_files:
  - .git/**
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_public_history_contract.py
required_reviews:
  - security
  - repository-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_public_history_contract.py -k no_history_rewrite"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-4 at=2026-07-24T20:50:23Z -->

# Record public-history handling without rewriting history

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write the failing contract test first. Record an owner and an accept, document, or separate-response decision, and forbid destructive history operations.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Record public-history handling without rewriting history
