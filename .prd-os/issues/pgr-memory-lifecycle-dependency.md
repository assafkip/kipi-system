---
id: pgr-memory-lifecycle-dependency
title: Replace the absolute memory-lifecycle symlink with a dependency contract
status: open
priority: p2
parent_prd: prd-portable-generated-runbooks-2026-07-24
allowed_files:
  - plugins/memory-lifecycle
  - plugins/dependencies.json
  - tests/test_plugin_dependencies.py
disallowed_files:
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
  - .git/**
required_checks:
  - python3 -m pytest -q tests/test_plugin_dependencies.py
required_reviews:
  - packaging-owner
bypass_check: "python3 -m pytest -q tests/test_plugin_dependencies.py -k 'absolute_symlink or missing_dependency'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-portable-generated-runbooks-2026-07-24 finding=finding-1 at=2026-07-24T21:13:00Z -->

# Replace the absolute memory-lifecycle symlink with a dependency contract

## Context

Parent PRD: `.prd-os/prds/prd-portable-generated-runbooks-2026-07-24.md`

## Acceptance

Write a failing fresh-clone broken-symlink test first. Declare source, version, install location, and required interface and fail clearly when absent.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Replace the absolute memory-lifecycle symlink with a dependency contract
