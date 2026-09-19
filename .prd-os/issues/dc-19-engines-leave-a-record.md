---
id: dc-19-engines-leave-a-record
title: Engine invocations are recorded and seal requires one for every engine a technique names
status: in-progress
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-engine-door.py
  - q-system/.q-system/scripts/test/test_dc_engine_records.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_engine_records.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_engine_records.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-26 at=2026-09-18T20:21:26Z -->

# Engine invocations are recorded and seal requires one for every engine a technique names

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

PostToolUse on Skill appends {skill, session, at} to the active round's engines.jsonl. A technique with an engine field and no matching record refuses the seal. Test: the copied-animation case.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Engine invocations are recorded and seal requires one for every engine a technique names
