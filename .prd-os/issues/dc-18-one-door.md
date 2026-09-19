---
id: dc-18-one-door
title: design-engine-door.py refuses a design engine outside an active round
status: in-progress
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-engine-door.py
  - q-system/.q-system/scripts/design-engines.json
  - q-system/.q-system/scripts/test/test_design_engine_door.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_design_engine_door.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_design_engine_door.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-25 at=2026-09-18T20:21:26Z -->

# design-engine-door.py refuses a design engine outside an active round

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

PreToolUse on the Skill tool. Reads design-engines.json (skill, lane, stage). A listed skill with no active round for the session exits 2 naming /design-chain; an unlisted skill exits 0; an unreadable registry exits 0 for unlisted names and 2 for the coded core list. Under 50 ms on the no-match path, asserted.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] design-engine-door.py refuses a design engine outside an active round
