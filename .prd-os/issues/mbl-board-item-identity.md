---
id: mbl-board-item-identity
title: Board items carry a stable id and a hand-moved item is never re-added
status: open
priority: p1
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/scripts/notion_board.py
  - q-system/.q-system/tests/test_notion_board.py
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - q-system/.q-system/scripts/morning-brief.py
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py -k moved_stays_moved"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-5 at=2026-09-01T22:00:59Z -->

# Board items carry a stable id and a hand-moved item is never re-added

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

Every item line ends with its stable id (Linear identifier or open-loop id). Before writing, the writer reads the whole page; any id found outside the top-of-mind block is excluded from the rewrite. RED first: fake page with ASK-402 in 'this week'; today's owed rows include ASK-402; after collect(), top-of-mind does not contain ASK-402 and 'this week' still does. Only the top-of-mind block is ever rewritten; a test asserts the other two blocks' request payloads are never sent.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Board items carry a stable id and a hand-moved item is never re-added
