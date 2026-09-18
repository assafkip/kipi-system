---
id: dc-25-rollout-proof
title: A script proves the fleet load path end to end
status: open
priority: p2
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-rollout-proof.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/design-chain-rollout-proof.sh --selftest
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/design-chain-rollout-proof.sh --selftest"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-30 at=2026-09-18T20:21:26Z -->

# A script proves the fleet load path end to end

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

The script checks: the marketplace clone holds the command; an instance root passed as an argument holds all design scripts and the hook entries; the gate hook run with CLAUDE_PROJECT_DIR set to that instance exits 2 on an unsealed page. --selftest runs it against a temp instance. The founder runs the fleet sync; this script is run against consulting afterwards and its output is pasted in the closeout.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] A script proves the fleet load path end to end
