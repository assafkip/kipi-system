---
id: lr-recall-names-its-corpus
title: lessons_recall.py takes an explicit corpus with stated precedence, prints which it read, and --both dedups by real path
status: closed
priority: p0
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - q-system/.q-system/scripts/lessons_recall.py
  - q-system/.q-system/tests/test_lessons_recall_corpus.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_recall_corpus.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_lessons_recall_corpus.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_lessons_recall_corpus.py -k 'names or both or dedup'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-14 at=2026-09-02T00:25:35Z -->

# lessons_recall.py takes an explicit corpus with stated precedence, prints which it read, and --both dedups by real path

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first: precedence is --corpus, then KIPI_LESSONS_DIR, then the file-relative default, pinned by a test that sets all three and asserts the corpus line; search prints 'corpus: <path> (<n>)' before its hits; --both adds every KIPI_LESSONS_CORPORA entry that exists after realpath resolution, drops duplicates (a symlink to the primary corpus is searched once, counts and ranking unchanged), reports a missing entry by name, and tags each hit with its corpus; the same query against two tmp corpora with different contents yields different hits AND the corpus line says which. Existing search/similar/duplicates/stats behaviour and exit codes unchanged (a test greps the tree for callers and runs one).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] lessons_recall.py takes an explicit corpus with stated precedence, prints which it read, and --both dedups by real path
