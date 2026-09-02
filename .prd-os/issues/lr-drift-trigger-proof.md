---
id: lr-drift-trigger-proof
title: Removing the trigger provably stops delivery: the reporter sends only under the plist's environment marker and has exactly one caller in the tree
status: open
priority: p1
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - q-system/.q-system/scripts/lessons-drift-report.py
  - q-system/.q-system/scripts/com.kipi.lessons-drift.plist
  - q-system/.q-system/tests/test_lessons_drift_report.py
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - q-system/.q-system/scripts/slack-notify.sh
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_lessons_drift_report.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_lessons_drift_report.py -k 'no_trigger or single_caller'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-7 at=2026-09-02T00:25:35Z -->

# Removing the trigger provably stops delivery: the reporter sends only under the plist's environment marker and has exactly one caller in the tree

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first: without KIPI_TRIGGER=launchd the reporter prints the report and calls deliver zero times (a fake deliver injected by the test counts calls); with it, deliver is called once; a source test enumerates every file in the tree (excluding .claude/worktrees/ and .wt-*) that names lessons-drift-report.py and asserts the set is exactly the plist template and the test itself, so a second caller or a removed template is RED; the 'stops when removed' launchd fact is still recorded at landing (install, kickstart, bootout, observe silence) as evidence, not as the proof.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Removing the trigger provably stops delivery: the reporter sends only under the plist's environment marker and has exactly one caller in the tree
