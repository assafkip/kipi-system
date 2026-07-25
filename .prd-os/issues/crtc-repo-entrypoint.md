---
id: crtc-repo-entrypoint
title: Create one repository test entrypoint and CI path
status: open
priority: p1
parent_prd: prd-complete-repo-test-contract-2026-07-24
allowed_files:
  - scripts/test-repo
  - .github/workflows/validate.yml
  - tests/test_repo_entrypoint.py
disallowed_files:
  - plugins/**/src/**
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_repo_entrypoint.py
  - scripts/test-repo --list
required_reviews:
  - ci-owner
bypass_check: "python3 -m pytest -q tests/test_repo_entrypoint.py -k failing_entry_propagates_nonzero"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-complete-repo-test-contract-2026-07-24 finding=finding-2 at=2026-07-24T21:01:37Z -->

# Create one repository test entrypoint and CI path

## Context

Parent PRD: `.prd-os/prds/prd-complete-repo-test-contract-2026-07-24.md`

## Acceptance

Write the failing aggregate-exit test first. Install declared test dependencies, execute every manifest entry, retain the skeleton capability gate, and fail on any red suite.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Create one repository test entrypoint and CI path
