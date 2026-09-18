---
id: dc-08-reader-runs-append
title: Reader runs append to one file and every run on the current page bytes counts
status: open
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-reader-gate.py
  - q-system/.q-system/scripts/test/test_dc_reader_runs.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_reader_runs.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_reader_runs.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-7 at=2026-09-18T20:21:26Z -->

# Reader runs append to one file and every run on the current page bytes counts

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

design-reader-gate.py opens gate/reader-runs.jsonl in append mode only. seal reads every row whose html_sha256 matches the current page, so a later all-STAY run does not erase an earlier LEAVE. Test: run LEAVE then STAY, seal still refuses.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Reader runs append to one file and every run on the current page bytes counts
