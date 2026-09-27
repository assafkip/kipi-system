---
id: dc-22-one-design-command-in-the-menu
title: Our design skills leave the menu and the design rules name the door
status: closed
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - .claude/rules/design-auto-invoke.md
  - .claude/rules/dogfood-gate.md
  - plugins/kipi-core/.claude-plugin/plugin.json
  - plugins/kipi-core/skills/deck-ai/SKILL.md
  - plugins/kipi-design/.claude-plugin/plugin.json
  - plugins/kipi-design/skills/*/SKILL.md
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/test/test_dc_one_door_menu.py
  - q-system/output/claude-proposals/*.json
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_one_door_menu.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_one_door_menu.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-28 at=2026-09-18T20:21:26Z -->

# Our design skills leave the menu and the design rules name the door

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

The four in-repo design skills carry user-invocable: false. Both rule files name design-engine-door.py and test_design_engine_door.py (edited through apply-claude-changes.sh). The test reads every SKILL.md the registry lists as ours and fails if one is user-invocable, and fails if a design skill exists in the plugins tree that the registry does not list.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Our design skills leave the menu and the design rules name the door
