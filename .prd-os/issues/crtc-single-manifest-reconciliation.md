---
id: crtc-single-manifest-reconciliation
title: Prove the capability manifest is the only test authority
status: open
priority: p1
parent_prd: prd-complete-repo-test-contract-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/test/test-single-test-manifest.sh
disallowed_files:
  - q-system/.q-system/capability-manifest.json
  - q-system/.q-system/scripts/capability-gate.py
  - plugins/**
  - .prd-os/**
required_checks:
  - bash q-system/.q-system/scripts/test/test-single-test-manifest.sh
required_reviews:
  - test-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-single-test-manifest.sh --reject-duplicate"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-complete-repo-test-contract-2026-07-24 finding=finding-6 at=2026-07-24T21:01:37Z -->

# Prove the capability manifest is the only test authority

## Context

Parent PRD: `.prd-os/prds/prd-complete-repo-test-contract-2026-07-24.md`

## Acceptance

Write a failing duplicate-manifest fixture first. Prove every repository test declaration resolves through the existing capability manifest and no second authority is introduced.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Prove the capability manifest is the only test authority
