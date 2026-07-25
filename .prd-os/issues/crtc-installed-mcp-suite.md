---
id: crtc-installed-mcp-suite
title: Run MCP tests as an installed package
status: open
priority: p1
parent_prd: prd-complete-repo-test-contract-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/pyproject.toml
  - plugins/kipi-core/kipi-mcp/tests/test_installed_package.py
disallowed_files:
  - plugins/kipi-core/kipi-mcp/src/**
  - .github/workflows/**
  - q-system/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_package.py
required_reviews:
  - packaging-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_package.py -k no_source_shadow"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-complete-repo-test-contract-2026-07-24 finding=finding-3 at=2026-07-24T21:01:37Z -->

# Run MCP tests as an installed package

## Context

Parent PRD: `.prd-os/prds/prd-complete-repo-test-contract-2026-07-24.md`

## Acceptance

Write a failing source-tree-shadowing test first. Build and install the package with declared test dependencies and run tests without repository import leakage.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Run MCP tests as an installed package
