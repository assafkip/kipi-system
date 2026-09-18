---
id: dc-21-fixtures-come-from-producers
title: Test fixtures carry provenance and the negative controls are permanent
status: open
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/test/dc_fixtures.py
  - q-system/.q-system/scripts/test/fixtures/design-chain/*
  - q-system/.q-system/scripts/test/test_dc_negative_controls.py
  - q-system/.q-system/scripts/test_design_chain_gate.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_negative_controls.py
  - python3 q-system/.q-system/scripts/test_design_chain_gate.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_negative_controls.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-23 at=2026-09-18T20:21:26Z -->

# Test fixtures carry provenance and the negative controls are permanent

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

dc_fixtures.load() refuses a fixture with no _provenance block (producer, command, captured_at). The ten hand-typed verdict lines are replaced. Rounds A, B, C and the bland control are tests that must never seal (A, B, bland) or must refuse (C).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Test fixtures carry provenance and the negative controls are permanent
