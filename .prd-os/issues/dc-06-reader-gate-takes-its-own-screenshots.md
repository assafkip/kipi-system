---
id: dc-06-reader-gate-takes-its-own-screenshots
title: design-reader-gate.py lives in the skeleton, shoots the served page itself, and rows carry the HTML and PNG shas
status: closed
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
- [x] design-reader-gate.py lives in the skeleton, shoots the served page itself, and rows carry the HTML and PNG shas (DELIVERED: design-reader-gate.py renders each page itself at the configured viewports, never reads a round PNG, rows carry html_sha256, png_sha256, keyed answers, contaminated, and provenance {runner, model, model_reported, persona_sha256, questions_sha256, attempts, at}; runner required, injected runner for tests. Real run: 6 rows, claude-haiku-4-5, 1 attempt each. Moved: served-round binding to ASK-1836, prompt injection to dc-07.)

## Amendments

### 2026-09-19T08:11:39Z
Reason: Production-path finding after round 2: the real model skipped or merged a question (9/8/9/9 answers over 4 calls), so the count check refused real runs. Sana: keyed answers + structural-only retries, in dc-06.

Before:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-reader-gate.py', 'q-system/.q-system/scripts/test/test_dc_reader_gate.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_reader_gate.py']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-reader-gate.py', 'q-system/.q-system/scripts/test/test_dc_reader_gate.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_reader_gate.py']
- disallowed_files: []
