---
id: lr-propagation-streak-escalation
title: lessons_streak.py owns the streak file atomically under one lock; lessons-daily.sh escalates on the Nth failure with the streak length
status: closed
priority: p0
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - q-system/.q-system/scripts/lessons_streak.py
  - q-system/.q-system/scripts/lessons-daily.sh
  - q-system/.q-system/tests/test_lessons_daily_streak.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_daily_streak.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - kipi-update.sh
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_streak.py -k 'streak or concurrent'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-9 at=2026-09-02T00:25:35Z -->

# lessons_streak.py owns the streak file atomically under one lock; lessons-daily.sh escalates on the Nth failure with the streak length

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first: the propagation step is injectable (KIPI_PROPAGATE_CMD) so a test forces N failures without kipi-update.sh; lessons_streak.py bump reads, changes and replaces the streak file by temp-file rename under an fcntl lock (a sibling .lock file), so 20 concurrent bumps yield exactly 20 and a reader never sees a partial file; a corrupt or missing file counts from zero; at streak 3 the log and notify lines differ from the streak-1 line and carry the number; one escalation row is appended per escalating run, none below the threshold; success resets to 0 with a logged 'streak reset after N'. A source test proves lessons-daily.sh writes the streak file only through lessons_streak.py. slack-notify.sh remains the alert sink for this job.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] lessons_streak.py owns the streak file atomically under one lock; lessons-daily.sh escalates on the Nth failure with the streak length
