---
id: memory-outcome-log
title: Outcome event log + single-writer record_outcome with event_id dedup
status: closed
priority: p1
parent_prd: prd-memory-outcome-scoring-2026-07-04
allowed_files:
  - q-system/.q-system/scripts/memory_outcomes.py
  - q-system/.q-system/scripts/test_memory_outcomes.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_memory_outcomes.py -q
required_reviews: []
bypass_check: "python3 -m pytest q-system/.q-system/scripts/test_memory_outcomes.py -q -k dedup"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-memory-outcome-scoring-2026-07-04 finding=finding-3 at=2026-07-04T19:38:51Z -->

# Outcome event log + single-writer record_outcome with event_id dedup

## Context

Parent PRD: `.prd-os/prds/prd-memory-outcome-scoring-2026-07-04.md`

## Acceptance

- [x] `record_outcome` is the only writer; appends one JSONL line per event to
  `q-system/memory/outcomes.jsonl`.
- [x] A duplicate `event_id` is refused (idempotent, no second line).
- [x] `read_events` skips malformed AND parseable-but-incomplete lines.
- [x] `pytest test_memory_outcomes.py -q` green (8 tests, incl. `-k dedup`).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Outcome event log + single-writer record_outcome with event_id dedup
