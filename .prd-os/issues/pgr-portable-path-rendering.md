---
id: pgr-portable-path-rendering
title: Normalize registry paths in canonical runbooks
status: open
priority: p2
parent_prd: prd-portable-generated-runbooks-2026-07-24
allowed_files:
  - tests/test_portable_registry_paths.py
disallowed_files:
  - instance-registry.json
  - scripts/generate-instance-docs.py
  - INSTANCES.md
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_portable_registry_paths.py
required_reviews:
  - docs-owner
bypass_check: "python3 -m pytest -q tests/test_portable_registry_paths.py -k source_username"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-portable-generated-runbooks-2026-07-24 finding=finding-7 at=2026-07-24T21:13:00Z -->

# Normalize registry paths in canonical runbooks

## Context

Parent PRD: `.prd-os/prds/prd-portable-generated-runbooks-2026-07-24.md`

## Acceptance

Write a failing source-username fixture first. Render managed paths with PROJECTS_ROOT, prove reversible expansion, and keep raw registry values untouched.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Normalize registry paths in canonical runbooks
