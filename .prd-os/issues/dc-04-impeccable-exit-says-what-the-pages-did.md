---
id: dc-04-impeccable-exit-says-what-the-pages-did
title: design-impeccable-check.py fails when a page raises an anti-pattern
status: open
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-impeccable-check.py
  - q-system/.q-system/scripts/test/test_dc_impeccable_exit.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_impeccable_exit.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_impeccable_exit.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-4 at=2026-09-18T20:21:26Z -->

# design-impeccable-check.py fails when a page raises an anti-pattern

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

Exit contract: 0 control fired and pages clean; 1 control did not fire; 2 could not run; 3 at least one page flagged. The value computed at worst = max(worst, rc) is consumed. seal refuses on 1, 2 and 3. Test drives the script with a stub detector.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] design-impeccable-check.py fails when a page raises an anti-pattern
