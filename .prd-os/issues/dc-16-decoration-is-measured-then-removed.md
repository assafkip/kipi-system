---
id: dc-16-decoration-is-measured-then-removed
title: The critique line count and byte-copy brief checks are measured, then deleted or re-bound
status: in-progress
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - plugins/kipi-core/.claude-plugin/plugin.json
  - plugins/kipi-core/commands/design-chain.md
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_decoration.py
  - q-system/.q-system/scripts/test_design_chain_gate.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_decoration.py
  - python3 q-system/.q-system/scripts/test_design_chain_gate.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_decoration.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-22 at=2026-09-18T20:21:26Z -->

# The critique line count and byte-copy brief checks are measured, then deleted or re-bound

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

First a script counts, across the sealed rounds on disk, what each check would have caught. Then each is deleted with its docs, or re-bound to an input the builder did not write. A test asserts the removed names stay gone.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] The critique line count and byte-copy brief checks are measured, then deleted or re-bound
