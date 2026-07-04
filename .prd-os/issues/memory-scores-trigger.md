---
id: memory-scores-trigger
title: Surface runs memory_reflect before reading the sidecar so it is fresh at SessionStart
status: open
priority: p1
parent_prd: prd-memory-outcome-scoring-2026-07-04
allowed_files:
  - q-system/.q-system/scripts/memory-scores-surface.py
  - q-system/.q-system/scripts/test_memory_scores_surface.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_memory_scores_surface.py -q
required_reviews: []
bypass_check: "python3 -m pytest q-system/.q-system/scripts/test_memory_scores_surface.py -q -k trigger"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-memory-outcome-scoring-2026-07-04 finding=finding-6 at=2026-07-04T19:38:51Z -->

# Surface runs memory_reflect before reading the sidecar so it is fresh at SessionStart

## Context

Parent PRD: `.prd-os/prds/prd-memory-outcome-scoring-2026-07-04.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Surface runs memory_reflect before reading the sidecar so it is fresh at SessionStart
