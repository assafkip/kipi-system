---
id: fcu-preservation-precondition
title: Fail closed before rsync when preservation proof fails
status: closed
priority: p0
parent_prd: prd-fail-closed-fleet-updater-2026-07-24
allowed_files:
  - kipi-update.sh
  - kipi-update-preserve-scan.py
  - test-kipi-update-preserve-scan.sh
  - q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh
  - q-system/.q-system/scripts/test/test-kipi-update-safety.sh
disallowed_files:
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
  - .git/**
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh
  - bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh
  - bash test-kipi-update-preserve-scan.sh
required_reviews:
  - updater-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh --assert-no-rsync"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-fail-closed-fleet-updater-2026-07-24 finding=finding-1 at=2026-07-24T20:57:37Z -->

# Fail closed before rsync when preservation proof fails

## Context

Parent PRD: `.prd-os/prds/prd-fail-closed-fleet-updater-2026-07-24.md`

## Acceptance

Write the failing helper-failure reproducer first. Prove rsync is never invoked without a complete snapshot and verified preservation receipt.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Fail closed before rsync when preservation proof fails

## Amendments

### 2026-07-24T23:14:21Z
Reason: Fail-closed helper precondition makes the existing updater safety fixture invalid unless it packages the production preservation helper; add that regression check to this issue.

Before:
- allowed_files: ['kipi-update.sh', 'q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh']
- disallowed_files: ['instance-registry.json', 'q-system/canonical/**', '.prd-os/**', '.git/**']

After:
- allowed_files: ['kipi-update.sh', 'q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh', 'q-system/.q-system/scripts/test/test-kipi-update-safety.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh', 'bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh']
- disallowed_files: ['instance-registry.json', 'q-system/canonical/**', '.prd-os/**', '.git/**']

### 2026-07-24T23:16:36Z
Reason: Codex major finding requires a helper-generated completion receipt and updater-side validation before rsync; include the helper and its regression test in scope.

Before:
- allowed_files: ['kipi-update.sh', 'q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh', 'q-system/.q-system/scripts/test/test-kipi-update-safety.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh', 'bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh']
- disallowed_files: ['instance-registry.json', 'q-system/canonical/**', '.prd-os/**', '.git/**']

After:
- allowed_files: ['kipi-update.sh', 'kipi-update-preserve-scan.py', 'test-kipi-update-preserve-scan.sh', 'q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh', 'q-system/.q-system/scripts/test/test-kipi-update-safety.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh', 'bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh', 'bash test-kipi-update-preserve-scan.sh']
- disallowed_files: ['instance-registry.json', 'q-system/canonical/**', '.prd-os/**', '.git/**']
