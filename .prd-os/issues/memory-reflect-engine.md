---
id: memory-reflect-engine
title: memory_reflect.py: decay + corroboration + contested + sidecar + source-fingerprint resolver
status: in-progress
priority: p1
parent_prd: prd-memory-outcome-scoring-2026-07-04
allowed_files:
  - q-system/.q-system/scripts/memory_reflect.py
  - q-system/.q-system/scripts/test_memory_reflect.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_memory_reflect.py -q
required_reviews: []
bypass_check: "python3 -m pytest q-system/.q-system/scripts/test_memory_reflect.py -q -k fingerprint"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-memory-outcome-scoring-2026-07-04 finding=finding-4 at=2026-07-04T19:38:51Z -->

# memory_reflect.py: decay + corroboration + contested + sidecar + source-fingerprint resolver

## Context

Parent PRD: `.prd-os/prds/prd-memory-outcome-scoring-2026-07-04.md`

## Acceptance

- [x] Signed time-decayed scoring (30d half-life); fresh dead end outweighs old useful.
- [x] Corroboration gate: >= 2 distinct `event_id` useful -> preferred; else tentative.
- [x] Contested (both signs, recency verdict from raw score); dead_ends (negative-only).
- [x] Deterministic byte-stable sidecar; source-fingerprint marks stale on change/vanish.
- [x] `pytest test_memory_reflect.py -q` green (11 tests, incl. `-k fingerprint`).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] memory_reflect.py: decay + corroboration + contested + sidecar + source-fingerprint resolver
