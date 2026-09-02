---
id: mbl-board-section-bounded
title: Notion board as a bounded pre-send section whose status is a line in the brief
status: closed
priority: p1
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/scripts/notion_board.py
  - q-system/.q-system/tests/test_notion_board.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_notion_board.py.json
  - q-system/.q-system/scripts/morning-brief.py
  - q-system/.q-system/tests/test_morning_brief.py
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py -k 'budget or pytest_refuses or never_ask'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-4 at=2026-09-01T22:00:59Z -->

# Notion board as a bounded pre-send section whose status is a line in the brief

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

A registered optional section (module stem notion_board). collect(now, owed_rows, opener=None, budget_s=20) writes top-of-mind then reads it back and returns rows ['board: written, read-back ok'] or error text; the caller's guard renders COULD NOT READ on raise or on exceeding the budget. RED first with a fake opener: (1) write then read-back agree on three items and the count; (2) an opener that sleeps past the budget yields 'board timed out (20s)'; (3) refuses under PYTEST_CURRENT_TEST like slack_founder.deliver; (4) source-text test: never reads NOTION_TOKEN_ASK, never names an ASK page id; (5) token and page id are read via Path.home() / '.config/kipi/', no /Users/ literal; missing page-id file means the section is absent, not an error.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Notion board as a bounded pre-send section whose status is a line in the brief (notion_board.py + the registry's None-means-off signal, recorded amendment; 11 tests red-first; mutation proof in the closing commit; 4 Codex findings accepted and patched: a shared cancellable budget so no write lands after a reported timeout, and the exact status row)

## Amendments

### 2026-09-01T22:55:45Z
Reason: The optional-section registry (issue mbl-brief-core) has no OFF signal: a present module always renders a section. The board's off-switch is 'no page-id file -> no section' (this issue's acceptance and mbl-off-switches), which needs the registry to treat a collector returning None as absent. Two lines in morning-brief.py collect_all() plus one test in test_morning_brief.py; the single-owner rule (finding-2) is honoured by keeping this the only registry change and by recording it here.

Before:
- allowed_files: ['q-system/.q-system/scripts/notion_board.py', 'q-system/.q-system/tests/test_notion_board.py', 'q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_notion_board.py.json']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**', 'q-system/.q-system/scripts/morning-brief.py']

After:
- allowed_files: ['q-system/.q-system/scripts/notion_board.py', 'q-system/.q-system/tests/test_notion_board.py', 'q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_notion_board.py.json', 'q-system/.q-system/scripts/morning-brief.py', 'q-system/.q-system/tests/test_morning_brief.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**']
