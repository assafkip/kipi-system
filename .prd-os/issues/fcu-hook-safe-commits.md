---
id: fcu-hook-safe-commits
title: Make updater commits pass active hooks without bypass
status: closed
priority: p0
parent_prd: prd-fail-closed-fleet-updater-2026-07-24
allowed_files:
  - kipi-update.sh
  - q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh
disallowed_files:
  - .githooks/**
  - lefthook.yml
  - instance-registry.json
  - .prd-os/**
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh
required_reviews:
  - enforcement-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh --reject-no-verify"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-fail-closed-fleet-updater-2026-07-24 finding=finding-4 at=2026-07-24T20:57:37Z -->

# Make updater commits pass active hooks without bypass

## Context

Parent PRD: `.prd-os/prds/prd-fail-closed-fleet-updater-2026-07-24.md`

## Acceptance

Write the failing no-verify reproducer first. Remove silent hook bypasses, abort on hook failure, and leave unrelated WIP outside updater commits.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Make updater commits pass active hooks without bypass
