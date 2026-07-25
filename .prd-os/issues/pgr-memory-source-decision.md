---
id: pgr-memory-source-decision
title: Resolve the memory-lifecycle source before symlink removal
status: open
priority: p2
parent_prd: prd-portable-generated-runbooks-2026-07-24
allowed_files:
  - plugins/memory-lifecycle-source.json
  - tests/test_memory_lifecycle_source.py
disallowed_files:
  - plugins/memory-lifecycle
  - plugins/dependencies.json
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_memory_lifecycle_source.py
required_reviews:
  - packaging-owner
bypass_check: "python3 -m pytest -q tests/test_memory_lifecycle_source.py -k missing_or_mutable"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-portable-generated-runbooks-2026-07-24 finding=finding-8 at=2026-07-24T21:13:00Z -->

# Resolve the memory-lifecycle source before symlink removal

## Context

Parent PRD: `.prd-os/prds/prd-portable-generated-runbooks-2026-07-24.md`

## Acceptance

Write a failing missing-source receipt test first. Record the authoritative remote, immutable version, interface owner, and retrieval proof before replacement can execute.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Resolve the memory-lifecycle source before symlink removal
