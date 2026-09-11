---
id: lr-drift-reporter
title: A scheduled drift reporter resolves skeleton and hubs from the registry, says what a hub has that the skeleton lacks, and appends the streak summary
status: closed
priority: p1
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - q-system/.q-system/scripts/lessons-drift-report.py
  - q-system/.q-system/scripts/com.kipi.lessons-drift.plist
  - q-system/.q-system/drift-hubs.json
  - q-system/.q-system/tests/test_lessons_drift_report.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_drift_report.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - q-system/.q-system/scripts/slack-notify.sh
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_lessons_drift_report.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_lessons_drift_report.py -k 'drift or could_not_read'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-13 at=2026-09-02T00:25:35Z -->

# A scheduled drift reporter resolves skeleton and hubs from the registry, says what a hub has that the skeleton lacks, and appends the streak summary

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first against two tmp trees and a fixture registry: the skeleton path is the registry's skeleton entry and must equal the reporter's own repo root, else COULD NOT READ (a worktree never reports as the skeleton); hubs are the registry names in drift-hubs.json, a name absent from the registry renders COULD NOT READ for that hub; the report lists lessons and scripts under q-system/.q-system/scripts/ present in the hub and absent from the skeleton, says 'no drift' when equal, appends lessons_streak.py summary, never references slack-notify.sh (source test), and delivers via slack_founder.deliver (refused under pytest, asserted). The plist template runs it Monday 06:45 with the placeholder shape and sets KIPI_TRIGGER=launchd in EnvironmentVariables.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] A scheduled drift reporter resolves skeleton and hubs from the registry, says what a hub has that the skeleton lacks, and appends the streak summary
