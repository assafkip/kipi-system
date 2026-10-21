---
id: dc-13-proof-has-a-shape
title: proof.md is parsed against a minimal schema
status: closed
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_proof_schema.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_proof_schema.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_proof_schema.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-24 at=2026-09-18T20:21:26Z -->

# proof.md is parsed against a minimal schema

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

Each artifact block names a proof kind from the closed list (problem, capability, reliability, outcome, pedigree) and a record id that resolves in the index file the config names. A one-character proof.md refuses.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] proof.md is parsed against a minimal schema
