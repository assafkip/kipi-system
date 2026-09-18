---
id: dc-05-seal-has-a-time-budget
title: Each producer run has a timeout and seal prints per-stage duration
status: open
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_seal_budget.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_seal_budget.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_seal_budget.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-16 at=2026-09-18T20:21:26Z -->

# Each producer run has a timeout and seal prints per-stage duration

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

Every producer subprocess carries a timeout read from config with a coded default; a timeout is a refusal naming the stage. seal prints one duration line per stage. Test uses a sleeping stub producer.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Each producer run has a timeout and seal prints per-stage duration
