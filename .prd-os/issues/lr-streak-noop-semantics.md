---
id: lr-streak-noop-semantics
title: A run that publishes nothing leaves the streak untouched; only a real propagation attempt bumps it
status: open
priority: p0
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - q-system/.q-system/scripts/lessons_streak.py
  - q-system/.q-system/scripts/lessons-daily.sh
  - q-system/.q-system/tests/test_lessons_daily_streak.py
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - kipi-update.sh
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py -k noop"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-10 at=2026-09-02T00:25:35Z -->

# A run that publishes nothing leaves the streak untouched; only a real propagation attempt bumps it

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first: the sequence fail, fail, nothing-new, nothing-new, held-only, fail leaves the streak at 3 (the three quiet runs neither reset nor increment and write nothing); the 'nothing new' early exit and the 'no propagation (nothing published)' branch touch neither the streak file nor the ledger (asserted by mtime and absence); the script header states the rule in one sentence and a source test pins that sentence next to the branch.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] A run that publishes nothing leaves the streak untouched; only a real propagation attempt bumps it
