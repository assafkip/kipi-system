---
id: mbl-draft-sent-pairing
title: Draft-vs-sent pairing by Gmail identity, unmatched drafts counted not guessed
status: open
priority: p1
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/scripts/draft-vs-sent.py
  - q-system/.q-system/tests/test_draft_vs_sent.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_draft_vs_sent.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - q-system/.q-system/data/metrics.db
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_draft_vs_sent.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_draft_vs_sent.py -k 'by_id or unmatched'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-7 at=2026-09-01T22:00:59Z -->

# Draft-vs-sent pairing by Gmail identity, unmatched drafts counted not guessed

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

Pairing is by Gmail message id only: drafts are read from q-system/output/drafts-ledger.jsonl (entries carry the Gmail draft message id; this issue defines the schema and the append helper the brief and /q-create will call) and each id is looked up in sent mail through the injectable runner seam. Subject, recipient or time similarity is never used. RED first: a fixture with two drafts sharing a subject pairs only the one whose id appears in sent mail; the other is reported in the output as unmatched with a count. Writes copy_edits rows into a tmp_path metrics.db in tests; never exemplars.jsonl.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Draft-vs-sent pairing by Gmail identity, unmatched drafts counted not guessed
