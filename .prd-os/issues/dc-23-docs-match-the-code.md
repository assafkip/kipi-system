---
id: dc-23-docs-match-the-code
title: The command doc matches the code and every RCA box is closed or voided
status: open
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - plugins/kipi-core/.claude-plugin/plugin.json
  - plugins/kipi-core/commands/design-chain.md
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/test/test_dc_command_doc.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_command_doc.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_command_doc.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-29 at=2026-09-18T20:21:26Z -->

# The command doc matches the code and every RCA box is closed or voided

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

test_dc_command_doc.py asserts every script path the command names exists, every stage the gate's stages list knows appears in the doc, and the doc has no step whose only holder is prose. The three RCAs' boxes are closed or voided against the code in the closeout note.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] The command doc matches the code and every RCA box is closed or voided
