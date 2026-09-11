---
id: mbl-board-live-readback
title: A live read-back check that fails closed without the token, required to close
status: closed
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
bypass_check: "python3 q-system/.q-system/scripts/notion_board.py --live-check"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-6 at=2026-09-01T22:00:59Z -->

# A live read-back check that fails closed without the token, required to close

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

notion_board.py --live-check writes a sentinel line to top-of-mind, reads it back, removes it, prints the page id and the round-trip time, and exits non-zero on missing token, missing page id, permission error, or mismatch. The bypass_check IS that live command, so this issue cannot close on a fake opener: it stays open until the founder places ~/.config/kipi/notion-token and notion-board-page. A pytest with a fake opener covers the mismatch and missing-credential branches RED first.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] A live read-back check that fails closed without the token, required to close (notion_board.py --live-check: per-invocation uuid sentinel, deletes only its own block, cleanup in finally; 7 tests red-first; 4 Codex findings accepted and patched. CLOSE IS BLOCKED BY DESIGN until the founder places ~/.config/kipi/notion-token and notion-board-page: the bypass_check ran 2026-09-01 and exited 3 'notion-board-page missing'. The issue is cleared, not closed; re-load, verify and close once the credential exists)
