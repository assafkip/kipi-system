---
id: dc-06-reader-gate-takes-its-own-screenshots
title: design-reader-gate.py lives in the skeleton, shoots the served page itself, and rows carry the HTML and PNG shas
status: in-progress
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-reader-gate.py
  - q-system/.q-system/scripts/test/test_dc_reader_gate.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_reader_gate.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_reader_gate.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-5 at=2026-09-18T20:21:26Z -->

# design-reader-gate.py lives in the skeleton, shoots the served page itself, and rows carry the HTML and PNG shas

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

New script in the skeleton. It renders each page at the configured viewports with playwright, hashes the PNG, and writes html_sha256 and png_sha256 into every row plus a _provenance block (model, persona sha, at). It never reads a PNG the round supplied. The model call is injectable so the test never spends one (PYTEST_CURRENT_TEST and an explicit runner argument).


One real model run on one page (a few cents) proves the render, hash and model path end to end; its row, with real provenance, is recorded in the closeout (Sana, 2026-09-19).


Answers are keyed by question number and a reader counts only with exactly keys 1..N; a wrong key set is retried up to 2 more times (never on what an answer says), provenance.attempts on every row, all-or-nothing after that. Measured on the real path 2026-09-19 before the change: 4 direct calls returned 9, 8, 9, 9 answers to 9 questions (Sana).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] design-reader-gate.py lives in the skeleton, shoots the served page itself, and rows carry the HTML and PNG shas
