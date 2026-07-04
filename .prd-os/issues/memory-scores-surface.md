---
id: memory-scores-surface
title: SessionStart earned-trust surface + MEMORY.md [contested]/[stale] index markers
status: in-progress
priority: p1
parent_prd: prd-memory-outcome-scoring-2026-07-04
allowed_files:
  - q-system/.q-system/scripts/memory-scores-surface.py
  - q-system/.q-system/scripts/test_memory_scores_surface.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_memory_scores_surface.py -q
required_reviews: []
bypass_check: "python3 -m pytest q-system/.q-system/scripts/test_memory_scores_surface.py -q -k marker"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-memory-outcome-scoring-2026-07-04 finding=finding-5 at=2026-07-04T19:38:51Z -->

# SessionStart earned-trust surface + MEMORY.md [contested]/[stale] index markers

## Context

Parent PRD: `.prd-os/prds/prd-memory-outcome-scoring-2026-07-04.md`

## Acceptance

- [x] `render_block` lists preferred / contested / stale, coverage-labeled; silent when empty.
- [x] `annotate_index` prefixes `[contested]`/`[stale]` only on real index lines; idempotent.
- [x] Non-index bullets and unknown slugs are left untouched; malformed sidecar never crashes.
- [x] `pytest test_memory_scores_surface.py -q` green (6 tests, incl. `-k marker`).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] SessionStart earned-trust surface + MEMORY.md [contested]/[stale] index markers
