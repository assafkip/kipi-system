---
id: autocapture-corrected-path
title: corrected outcome via learn-from-correction: conservative memory_id mapping with a deterministic check
status: in-progress
priority: p1
parent_prd: prd-memory-autocapture-2026-07-04
allowed_files:
  - plugins/kipi-core/skills/learn-from-correction/SKILL.md
  - q-system/.q-system/scripts/correction_outcome.py
  - q-system/.q-system/scripts/test_correction_outcome.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test_correction_outcome.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test_correction_outcome.py"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-memory-autocapture-2026-07-04 finding=finding-6 at=2026-07-04T21:08:45Z -->

# corrected outcome via learn-from-correction: conservative memory_id mapping with a deterministic check

## Context

Parent PRD: `.prd-os/prds/prd-memory-autocapture-2026-07-04.md`

## Acceptance

learn-from-correction, when a contradicted belief maps to a surfaced memory_id, records one corrected outcome via record_outcome (a small correction_outcome.py helper holds the deterministic map-then-record logic the skill invokes). Conservative: no confident map means no write. Test proves: mapped correction produces exactly one corrected line; unmapped correction produces zero writes; replay is idempotent.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] corrected outcome via learn-from-correction: conservative memory_id mapping with a deterministic check
