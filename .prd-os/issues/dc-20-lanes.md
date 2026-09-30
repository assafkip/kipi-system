---
id: dc-20-lanes
title: /design-chain takes a lane and the receipt says which stages a lane does not run
status: closed
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - plugins/kipi-core/.claude-plugin/plugin.json
  - plugins/kipi-core/commands/design-chain.md
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-engines.json
  - q-system/.q-system/scripts/test/test_dc_lanes.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_lanes.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_lanes.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-27 at=2026-09-18T20:21:26Z -->

# /design-chain takes a lane and the receipt says which stages a lane does not run

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

craft-manifest.json declares lane in {site, brand, deck, motion}; default site. Non-site lanes skip the web-only measuring stages and the stages list records them as 'not applicable: lane', never as passed. Readers run on the rendered output the reader gate shoots or is handed by the lane's engine record.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] /design-chain takes a lane and the receipt says which stages a lane does not run
