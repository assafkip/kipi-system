---
id: fcu-owned-state-manifest
title: Preserve tracked and untracked registry-derived owned state
status: closed
priority: p0
parent_prd: prd-fail-closed-fleet-updater-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/update-preservation-manifest.py
  - q-system/.q-system/scripts/test/test-update-preservation-manifest.py
disallowed_files:
  - kipi-update.sh
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 q-system/.q-system/scripts/test/test-update-preservation-manifest.py
required_reviews:
  - updater-owner
bypass_check: "python3 q-system/.q-system/scripts/test/test-update-preservation-manifest.py --negative-layouts"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-fail-closed-fleet-updater-2026-07-24 finding=finding-3 at=2026-07-24T20:57:37Z -->

# Preserve tracked and untracked registry-derived owned state

## Context

Parent PRD: `.prd-os/prds/prd-fail-closed-fleet-updater-2026-07-24.md`

## Acceptance

Write failing tracked, untracked, null-prefix, custom-q-dir, and standalone fixtures first. Cover canonical, project, memory, output, bus, and instance automation.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Preserve tracked and untracked registry-derived owned state
