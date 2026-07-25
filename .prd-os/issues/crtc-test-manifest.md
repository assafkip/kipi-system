---
id: crtc-test-manifest
title: Enumerate every shipped test and enforcement path
status: open
priority: p1
parent_prd: prd-complete-repo-test-contract-2026-07-24
allowed_files:
  - q-system/.q-system/capability-manifest.json
  - q-system/.q-system/scripts/capability-gate.py
  - q-system/.q-system/scripts/test_capability_gate.py
disallowed_files:
  - .github/workflows/**
  - plugins/**/src/**
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/scripts/test_capability_gate.py
required_reviews:
  - test-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/scripts/test_capability_gate.py -k undeclared"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-complete-repo-test-contract-2026-07-24 finding=finding-1 at=2026-07-24T21:01:37Z -->

# Enumerate every shipped test and enforcement path

## Context

Parent PRD: `.prd-os/prds/prd-complete-repo-test-contract-2026-07-24.md`

## Acceptance

Write a failing undeclared-artifact fixture first. Enumerate shipped plugin suites, script tests, self-tests, and enforcement hooks with owned exemptions.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Enumerate every shipped test and enforcement path
