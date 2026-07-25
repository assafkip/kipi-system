---
id: crtc-design-publish-package
title: Package and test the design publish-gate boundary
status: open
priority: p1
parent_prd: prd-complete-repo-test-contract-2026-07-24
allowed_files:
  - plugins/kipi-design/pyproject.toml
  - plugins/kipi-design/hooks/publish_gate.py
  - plugins/kipi-design/design_room/**
  - plugins/kipi-design/hooks/tests/test_publish_gate.py
disallowed_files:
  - .github/workflows/**
  - plugins/kipi-core/**
  - q-system/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-design/hooks/tests/test_publish_gate.py
  - python3 plugins/kipi-design/hooks/publish_gate.py --self-test
required_reviews:
  - design-owner
  - packaging-owner
bypass_check: "python3 -m pytest -q plugins/kipi-design/hooks/tests/test_publish_gate.py -k missing_executor"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-complete-repo-test-contract-2026-07-24 finding=finding-5 at=2026-07-24T21:01:37Z -->

# Package and test the design publish-gate boundary

## Context

Parent PRD: `.prd-os/prds/prd-complete-repo-test-contract-2026-07-24.md`

## Acceptance

Write a failing installed-boundary test first. Package the executor with kipi-design or make the gate self-contained, then run its self-test from the installed artifact.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Package and test the design publish-gate boundary
