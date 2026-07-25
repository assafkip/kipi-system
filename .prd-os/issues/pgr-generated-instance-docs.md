---
id: pgr-generated-instance-docs
title: Generate fleet counts and paths from the registry
status: open
priority: p2
parent_prd: prd-portable-generated-runbooks-2026-07-24
allowed_files:
  - scripts/generate-instance-docs.py
  - INSTANCES.md
  - tests/test_generated_instance_docs.py
disallowed_files:
  - instance-registry.json
  - q-system/canonical/**
  - .prd-os/**
  - .git/**
required_checks:
  - python3 -m pytest -q tests/test_generated_instance_docs.py
  - python3 scripts/generate-instance-docs.py --check
required_reviews:
  - docs-owner
bypass_check: "python3 -m pytest -q tests/test_generated_instance_docs.py -k registry_change"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-portable-generated-runbooks-2026-07-24 finding=finding-2 at=2026-07-24T21:13:00Z -->

# Generate fleet counts and paths from the registry

## Context

Parent PRD: `.prd-os/prds/prd-portable-generated-runbooks-2026-07-24.md`

## Acceptance

Write a failing stale-count and raw-home-path fixture first. Generate stable count, PROJECTS_ROOT-normalized path, type, subtree_prefix, and instance_q_dir fields without changing the registry.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Generate fleet counts and paths from the registry
