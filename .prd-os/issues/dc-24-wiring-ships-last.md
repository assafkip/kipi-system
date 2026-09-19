---
id: dc-24-wiring-ships-last
title: Hook entries and the plugin command ship only after round A refuses
status: in-progress
priority: p2
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - .claude/settings.json
  - plugins/kipi-core/.claude-plugin/plugin.json
  - plugins/kipi-core/commands/design-chain.md
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/settings-template-sync-check.py
  - q-system/.q-system/scripts/test/test_dc_negative_controls.py
  - q-system/.q-system/scripts/test/test_dc_wiring.py
  - q-system/output/claude-proposals/*.json
  - settings-template.json
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_wiring.py
  - python3 q-system/.q-system/scripts/test/test_dc_negative_controls.py
  - python3 q-system/.q-system/scripts/settings-template-sync-check.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_wiring.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-10 at=2026-09-18T20:21:26Z -->

# Hook entries and the plugin command ship only after round A refuses

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

Adds the gate's three hook entries and the door's two to settings-template.json and .claude/settings.json (the latter through apply-claude-changes.sh). test_dc_wiring.py runs each wired command the way the harness does (stdin JSON, CLAUDE_PROJECT_DIR set) and asserts the exit codes, and asserts no .claude/commands/design-chain.md exists. Depends on every other issue being closed.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Hook entries and the plugin command ship only after round A refuses
