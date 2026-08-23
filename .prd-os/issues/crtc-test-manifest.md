---
id: crtc-test-manifest
title: Enumerate every shipped test and enforcement path
status: closed
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
  - python3 q-system/.q-system/scripts/test_capability_gate.py
required_reviews:
  - test-owner
# sp-4c5a00f3: test_capability_gate.py is a main()-based harness with sec_*
# sections; pytest collects ZERO tests from it, so the pytest form returned
# rc=5 forever and could never fail. Same trap crtc-one-canonical-resolver's
# spec documents (finding-3, finding-29). The direct invocation exits 1 on a
# broken manifest and 0 on a healthy one.
bypass_check: "python3 q-system/.q-system/scripts/test_capability_gate.py"
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
- [x] Enumerate every shipped test and enforcement path
