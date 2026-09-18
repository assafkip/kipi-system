---
id: dc-01-carry-the-real-file-set
title: Carry the 12 design-chain files onto main with a dependency census taken by code
status: open
priority: p0
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/check_technique_parity.py
  - q-system/.q-system/scripts/design-*.py
  - q-system/.q-system/scripts/test/test_dc_dependency_census.py
  - q-system/.q-system/scripts/test/test_design_chain_vision_stage.py
  - q-system/.q-system/scripts/test_design_chain_gate.py
  - q-system/.q-system/scripts/test_design_standard_check.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_dependency_census.py
  - python3 q-system/.q-system/scripts/test_design_chain_gate.py
  - python3 q-system/.q-system/scripts/test/test_design_chain_vision_stage.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_dependency_census.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-2 at=2026-09-18T20:21:26Z -->

# Carry the 12 design-chain files onto main with a dependency census taken by code

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

All 8 design-*.py scripts, check_technique_parity.py and the 3 tests exist on the branch with NO hook wiring. test_dc_dependency_census.py follows static imports AND _load_sibling / spec_from_file_location loads, fails when a loaded sibling is absent, and pins the declared third-party set (playwright, Pillow). Mutation: delete design-ink-coverage.py, the census goes red.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Carry the 12 design-chain files onto main with a dependency census taken by code
