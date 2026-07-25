---
id: pff-baseline-lifecycle
title: Prune stale baseline entries and report adds separately from removals
status: open
priority: p1
parent_prd: prd-prevent-fact-fanout-2026-07-25
allowed_files:
  - q-system/.q-system/scripts/propagation-leak-gate.py
  - q-system/.q-system/scripts/test/test-propagation-leak-baseline.py
disallowed_files:
  - kipi-update.sh
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-baseline.py
required_reviews:
  - updater-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-leak-baseline.py -k 'stale and pruned'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-prevent-fact-fanout-2026-07-25 finding=finding-7 at=2026-07-25T18:11:12Z -->

# Prune stale baseline entries and report adds separately from removals

## Context

Parent PRD: `.prd-os/prds/prd-prevent-fact-fanout-2026-07-25.md`

## Acceptance

Write the failing stale-entry reproducer first. Re-baselining prunes fingerprints whose findings are gone and reports adds and removals as separate sets.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Prune stale baseline entries and report adds separately from removals
