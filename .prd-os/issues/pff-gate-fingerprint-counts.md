---
id: pff-gate-fingerprint-counts
title: Fingerprint leak findings with occurrence counts
status: in-progress
priority: p0
parent_prd: prd-prevent-fact-fanout-2026-07-25
allowed_files:
  - q-system/.q-system/scripts/propagation-leak-gate.py
  - q-system/.q-system/scripts/test/test-propagation-leak-gate.py
disallowed_files:
  - kipi-update.sh
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-gate.py
required_reviews:
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-gate.py -k 'count and replay'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-prevent-fact-fanout-2026-07-25 finding=finding-4 at=2026-07-25T18:11:12Z -->

# Fingerprint leak findings with occurrence counts

## Context

Parent PRD: `.prd-os/prds/prd-prevent-fact-fanout-2026-07-25.md`

## Acceptance

Write the failing duplicate-and-reintroduce reproducer first. A baselined line duplicated, removed and re-added, or reused for another record must register as new.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Fingerprint leak findings with occurrence counts
