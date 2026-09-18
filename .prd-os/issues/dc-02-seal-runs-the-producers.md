---
id: dc-02-seal-runs-the-producers
title: seal runs the standard and gap producers itself and uses their exit codes
status: in-progress
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_seal_runs_producers.py
  - q-system/.q-system/scripts/test_design_chain_gate.py
  - q-system/.q-system/scripts/test/stub_producers/*
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_seal_runs_producers.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_seal_runs_producers.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-18 at=2026-09-18T20:21:26Z -->

# seal runs the standard and gap producers itself and uses their exit codes

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

seal invokes design-standard-check.py and design-gap-check.py (when craft.require_gap_check) and refuses on a nonzero exit; a standard.json or gap.json typed by hand with pass true does not seal. Exit 2 from a producer prints 'could not measure' and refuses.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] seal runs the standard and gap producers itself and uses their exit codes
