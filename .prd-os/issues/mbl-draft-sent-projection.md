---
id: mbl-draft-sent-projection
title: Only a diff projection is stored: no raw bodies, hashed recipients, 90-day purge
status: open
priority: p1
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/scripts/draft-vs-sent.py
  - q-system/.q-system/tests/test_draft_vs_sent.py
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - q-system/.q-system/data/metrics.db
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_draft_vs_sent.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_draft_vs_sent.py -k 'no_raw_body or purge'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-8 at=2026-09-01T22:00:59Z -->

# Only a diff projection is stored: no raw bodies, hashed recipients, 90-day purge

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

The stored copy_edits row holds a unified diff of draft vs sent, recipient addresses replaced by a salted hash, no subject and no headers; original/edited columns receive the diff halves, never the full bodies. RED first: a test plants a recipient address and a unique body sentence and asserts neither appears anywhere in the stored row; --purge deletes rows older than 90 days and reports the count, and a test proves a 91-day-old row goes and an 89-day-old row stays.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Only a diff projection is stored: no raw bodies, hashed recipients, 90-day purge
