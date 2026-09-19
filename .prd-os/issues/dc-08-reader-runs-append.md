---
id: dc-08-reader-runs-append
title: Reader runs append to one file and every run on the current page bytes counts
status: in-progress
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-reader-gate.py
  - q-system/.q-system/scripts/test/test_dc_reader_runs.py
  - q-system/.q-system/scripts/test/test_dc_reader_verdicts.py
  - q-system/.q-system/scripts/test/test_dc_reader_gate.py
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

From dc-07's reviews (Sana, 2026-09-19; dc-07 adv-3, adv-4, adv-5 and std-1, rejected there with this issue as the follow-up):

Each design-reader-gate.py invocation gets a run_id recorded in every row it writes, plus the readers config it ran under: n, viewports, labels, narrow, floor, persona_sha256, model. seal groups rows by run_id and counts a run complete only when it holds every expected id for the page. Among complete runs for the current page bytes, seal counts only the run(s) whose recorded config equals today's design-chain.json readers block; a floor or n lowered after a run recorded a higher one refuses instead of passing. Any LEAVE or narrow label in ANY complete run for the current bytes refuses. Reader rows present in reader-runs.jsonl for this page with no readers block in design-chain.json refuses at seal (closes deleting the config to escape a LEAVE). Test: two separate runs with different run_ids, rows spliced from each into one page's set so no run_id is complete; seal refuses for lack of a complete run, not for the spliced verdicts.

A run with --page for one page of a multi-page round leaves every other page's rows in the file (std-1: it overwrote them, and seal then refused the other page with no reader rows). Test: read PageA, then PageB, seal sees rows for both.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Reader runs append to one file and every run on the current page bytes counts
