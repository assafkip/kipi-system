---
id: pgr-updater-manifest-consumer
title: Prove updater and docs consume one behavior authority
status: open
priority: p2
parent_prd: prd-portable-generated-runbooks-2026-07-24
allowed_files:
  - tests/test_updater_behavior_authority.py
disallowed_files:
  - kipi-update.sh
  - UPDATE.md
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_updater_behavior_authority.py
required_reviews:
  - updater-owner
bypass_check: "python3 -m pytest -q tests/test_updater_behavior_authority.py -k unconsumed_phase"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-portable-generated-runbooks-2026-07-24 finding=finding-6 at=2026-07-24T21:13:00Z -->

# Prove updater and docs consume one behavior authority

## Context

Parent PRD: `.prd-os/prds/prd-portable-generated-runbooks-2026-07-24.md`

## Acceptance

Write a failing unconsumed-phase test first. Require every executable updater phase and every generated runbook section to derive from the same manifest.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Prove updater and docs consume one behavior authority
