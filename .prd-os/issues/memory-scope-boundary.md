---
id: memory-scope-boundary
title: Scope scoring to q-system/memory only; record_outcome rejects out-of-scope memory_id
status: open
priority: p1
parent_prd: prd-memory-outcome-scoring-2026-07-04
allowed_files:
  - q-system/.q-system/scripts/memory_outcomes.py
  - q-system/.q-system/scripts/test_memory_outcomes.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_memory_outcomes.py -q
required_reviews: []
bypass_check: "python3 -m pytest q-system/.q-system/scripts/test_memory_outcomes.py -q -k scope"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-memory-outcome-scoring-2026-07-04 finding=finding-1 at=2026-07-04T19:38:51Z -->

# Scope scoring to q-system/memory only; record_outcome rejects out-of-scope memory_id

## Context

Parent PRD: `.prd-os/prds/prd-memory-outcome-scoring-2026-07-04.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Scope scoring to q-system/memory only; record_outcome rejects out-of-scope memory_id
