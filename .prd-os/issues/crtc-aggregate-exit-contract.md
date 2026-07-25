---
id: crtc-aggregate-exit-contract
title: Prove any failing suite makes the repository entrypoint red
status: open
priority: p1
parent_prd: prd-complete-repo-test-contract-2026-07-24
allowed_files:
  - tests/test_repo_entrypoint_failures.py
disallowed_files:
  - scripts/test-repo
  - .github/workflows/**
  - plugins/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_repo_entrypoint_failures.py
required_reviews:
  - ci-owner
bypass_check: "python3 -m pytest -q tests/test_repo_entrypoint_failures.py -k every_red_propagates"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-complete-repo-test-contract-2026-07-24 finding=finding-7 at=2026-07-24T21:01:37Z -->

# Prove any failing suite makes the repository entrypoint red

## Context

Parent PRD: `.prd-os/prds/prd-complete-repo-test-contract-2026-07-24.md`

## Acceptance

Write a failing aggregate-exit fixture first. Inject one red manifest entry and require scripts/test-repo to preserve a nonzero final exit.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Prove any failing suite makes the repository entrypoint red
