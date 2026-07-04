---
id: autocapture-e2e-acceptance
title: Deterministic end-to-end acceptance: auto-captured outcomes move memory_reflect verdicts
status: in-progress
priority: p2
parent_prd: prd-memory-autocapture-2026-07-04
allowed_files:
  - q-system/.q-system/scripts/test_autocapture_e2e.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test_autocapture_e2e.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test_autocapture_e2e.py"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-memory-autocapture-2026-07-04 finding=finding-2 at=2026-07-04T21:08:45Z -->

# Deterministic end-to-end acceptance: auto-captured outcomes move memory_reflect verdicts

## Context

Parent PRD: `.prd-os/prds/prd-memory-autocapture-2026-07-04.md`

## Acceptance

Replaces the vague success language with a deterministic threshold: a seeded design-partner-realistic session set is fed through capture (artifact + capture-core + corrected), then memory_reflect.aggregate is asserted to move >= 1 memory to preferred (>= 2 distinct useful event_ids) and >= 1 memory to dead_end, using ONLY auto-captured outcomes (no manual CLI lines). Read-only over the other issues' code; test-only, no source overlap.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Deterministic end-to-end acceptance: auto-captured outcomes move memory_reflect verdicts
