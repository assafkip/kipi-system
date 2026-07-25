---
id: pff-baseline-provenance
title: Require per-entry justification for a baselined high-confidence fact
status: closed
priority: p0
parent_prd: prd-prevent-fact-fanout-2026-07-25
allowed_files:
  - q-system/.q-system/scripts/propagation-leak-gate.py
  - q-system/.q-system/state/propagation-leak-baseline.json
  - q-system/.q-system/scripts/test/test-propagation-leak-baseline.py
disallowed_files:
  - kipi-update.sh
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-baseline.py
required_reviews:
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-baseline.py -k 'bulk_accept and refused'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-prevent-fact-fanout-2026-07-25 finding=finding-5 at=2026-07-25T18:11:12Z -->

# Require per-entry justification for a baselined high-confidence fact

## Context

Parent PRD: `.prd-os/prds/prd-prevent-fact-fanout-2026-07-25.md`

## Acceptance

Write the failing bulk-accept reproducer first. Blocking scope is the six high-confidence classes; every baselined entry in those classes carries a justification and a bulk accept without one is refused.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Require per-entry justification for a baselined high-confidence fact
