---
id: pff-all-propagation-entrypoints
title: Run the gate on every path that copies generic content into an instance
status: in-progress
priority: p0
parent_prd: prd-prevent-fact-fanout-2026-07-25
allowed_files:
  - kipi-new-instance.sh
  - kipi-migrate.py
  - build-template-repo.sh
  - q-system/.q-system/scripts/test/test-propagation-entrypoints.py
disallowed_files:
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-entrypoints.py
required_reviews:
  - updater-owner
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/scripts/test/test-propagation-entrypoints.py -k 'every_entrypoint and gated'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-prevent-fact-fanout-2026-07-25 finding=finding-3 at=2026-07-25T18:11:12Z -->

# Run the gate on every path that copies generic content into an instance

## Context

Parent PRD: `.prd-os/prds/prd-prevent-fact-fanout-2026-07-25.md`

## Acceptance

Write the failing entry-point-inventory reproducer first. Enumerate every script that copies generic content into an instance and prove each one calls the gate before copying.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Run the gate on every path that copies generic content into an instance
