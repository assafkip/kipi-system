---
id: lr-escalations-ledger-reader
title: The escalations ledger gets a reader (summary) and a bound (last 200 rows)
status: closed
priority: p1
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
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py -k 'summary or retention'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-8 at=2026-09-02T00:25:35Z -->

# The escalations ledger gets a reader (summary) and a bound (last 200 rows)

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first: lessons_streak.py summary prints the current streak and the escalation rows of the last 30 days as one line and as JSON; append-escalation truncates the ledger to its last 200 rows (250 appended, 200 remain, the newest kept); the escalated notify line includes 'N escalations in 30d' read from summary; a ledger with one malformed row still summarises the rest and names the bad line count. The drift reporter (issue 13) is the second reader.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] The escalations ledger gets a reader (summary) and a bound (last 200 rows)
