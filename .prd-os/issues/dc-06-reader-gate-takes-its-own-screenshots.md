---
id: dc-06-reader-gate-takes-its-own-screenshots
title: design-reader-gate.py lives in the skeleton, shoots the served page itself, and rows carry the HTML and PNG shas
status: open
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

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] design-reader-gate.py lives in the skeleton, shoots the served page itself, and rows carry the HTML and PNG shas
