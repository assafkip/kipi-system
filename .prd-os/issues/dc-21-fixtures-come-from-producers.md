---
id: dc-21-fixtures-come-from-producers
title: Test fixtures carry provenance and the negative controls are permanent
status: closed
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

dc_fixtures.load() refuses a fixture with no _provenance block (producer, command, captured_at). The eight hand-typed checks/impeccable.txt receipts are replaced by producer captures. checks/bio_gate.txt capture moves to dc-11 and gate/icp.md capture to dc-07 (Sana, 2026-09-19): the gate reads neither file's content until those issues land. The mutation run (N1-N4, mutation and killing test each) is recorded in the negative-controls test docstring. Round B never reaches COMPLETE. Control C is redefined: round A with a page that fails the real standard producer must refuse; removing that refusal from the gate turns C red (mutation run recorded). The bland control (no colour, no motion, four lines of text) sealed at the craft tier against the exemplar captures (captured with provenance) and a real screenshot must refuse, naming at least one design axis below the exemplar floor (measured 2026-09-19: background colours, transitions, corner radii, fold controls, type sizes). Round A moves to dc-07 and A-checks to dc-11 as their RED FIRST tests (Sana, 2026-09-19): round A still seals today because nothing reads reader verdicts or check results.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Test fixtures carry provenance and the negative controls are permanent (DELIVERED: dc_fixtures.load refuses a fixture without a non-blank producer/command/captured_at or with edited or non-text content; the eight typed impeccable receipts load a real capture; round B never COMPLETE, control C refuses on a real standard FAIL, the bland page refuses at the craft tier on design axes; N1-N4 recorded. Moved: round A to dc-07, A-checks and bio_gate capture to dc-11, icp capture to dc-07.)

## Amendments

### 2026-09-19T06:34:32Z
Reason: Sana triage of 3bdda338 reviews: count corrected to the eight impeccable receipts; bio_gate.txt and icp.md capture move to dc-11 and dc-07; mutation run recorded in the test docstring.

Before:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/test/dc_fixtures.py', 'q-system/.q-system/scripts/test/fixtures/design-chain/*', 'q-system/.q-system/scripts/test/test_dc_negative_controls.py', 'q-system/.q-system/scripts/test_design_chain_gate.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_negative_controls.py', 'python3 q-system/.q-system/scripts/test_design_chain_gate.py']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/test/dc_fixtures.py', 'q-system/.q-system/scripts/test/fixtures/design-chain/*', 'q-system/.q-system/scripts/test/test_dc_negative_controls.py', 'q-system/.q-system/scripts/test_design_chain_gate.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_negative_controls.py', 'python3 q-system/.q-system/scripts/test_design_chain_gate.py']
- disallowed_files: []
