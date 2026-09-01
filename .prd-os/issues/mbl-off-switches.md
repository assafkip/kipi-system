---
id: mbl-off-switches
title: Every new job and writer has an off-switch, proven a no-op in the off state
status: open
priority: p1
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/tests/test_off_switches.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_off_switches.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - q-system/.q-system/scripts/morning-brief.py
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_off_switches.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_off_switches.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-17 at=2026-09-01T22:00:59Z -->

# Every new job and writer has an off-switch, proven a no-op in the off state

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

Runs LAST. RED first against each module by import with tmp_path homes: (1) notion_board with no page-id file yields no section and no network call (fake opener asserts zero requests); (2) weekly-improve.sh --dry-run with no plist installed performs no writes; (3) weekly-improve.py with no friction.jsonl renders 'nothing this week' and sends nothing (slack_founder refuses under pytest and the test asserts refused, not delivered); (4) improve_ground.py is importable without side effects. A test that sets its own precondition is not enough (lesson): each case asserts the absence of the artifact the on-state would have produced.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Every new job and writer has an off-switch, proven a no-op in the off state
