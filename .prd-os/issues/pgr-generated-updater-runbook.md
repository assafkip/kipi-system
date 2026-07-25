---
id: pgr-generated-updater-runbook
title: Generate updater behavior from executable configuration
status: open
priority: p2
parent_prd: prd-portable-generated-runbooks-2026-07-24
allowed_files:
  - q-system/.q-system/config/updater-behavior.json
  - kipi-update.sh
  - scripts/generate-updater-docs.py
  - UPDATE.md
  - tests/test_generated_updater_docs.py
disallowed_files:
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
  - .git/**
required_checks:
  - python3 -m pytest -q tests/test_generated_updater_docs.py
  - python3 scripts/generate-updater-docs.py --check
required_reviews:
  - updater-owner
  - docs-owner
bypass_check: "python3 -m pytest -q tests/test_generated_updater_docs.py -k executable_drift"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-portable-generated-runbooks-2026-07-24 finding=finding-3 at=2026-07-24T21:13:00Z -->

# Generate updater behavior from executable configuration

## Context

Parent PRD: `.prd-os/prds/prd-portable-generated-runbooks-2026-07-24.md`

## Acceptance

Write a failing behavior-drift fixture first. Make the updater and generator consume one versioned behavior manifest covering preserved paths, phases, dry-run behavior, commit behavior, and rollback references.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Generate updater behavior from executable configuration
