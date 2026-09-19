---
id: dc-15-exemplars-fail-loudly
title: A malformed exemplars.json refuses, and exemplar citation has a floor
status: closed
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_exemplars.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_exemplars.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_exemplars.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-21 at=2026-09-18T20:21:26Z -->

# A malformed exemplars.json refuses, and exemplar citation has a floor

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

The except ValueError: named = [] branch becomes a refusal. directions.md must cite at least the configured floor of exemplars (default: all of them up to 3).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] A malformed exemplars.json refuses, and exemplar citation has a floor
