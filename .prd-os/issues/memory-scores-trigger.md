---
id: memory-scores-trigger
title: Surface runs memory_reflect before reading the sidecar so it is fresh at SessionStart
status: closed
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

- [x] `main()` rebuilds the sidecar from the outcomes log BEFORE reading it.
- [x] Refresh is atomic (temp + os.replace) and best-effort; a failure preserves
  the old sidecar and never crashes SessionStart.
- [x] `pytest test_memory_scores_surface.py -q` green (9 tests, incl. `-k trigger`).
- Note: live SessionStart registration in settings.json is captured as spillover
  sp-04006168 (no issue in this PRD scoped settings.json).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Surface runs memory_reflect before reading the sidecar so it is fresh at SessionStart
