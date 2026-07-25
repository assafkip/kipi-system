---
id: srsa-registry-state-root-fixtures
title: Cover registry-derived state-root variants
status: open
priority: p0
parent_prd: prd-single-runtime-state-authority-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/tests/test_registry_state_roots.py
disallowed_files:
  - plugins/kipi-core/kipi-mcp/src/**
  - q-system/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_registry_state_roots.py
required_reviews:
  - runtime-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_registry_state_roots.py -k 'null_subtree or updater_delete'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-single-runtime-state-authority-2026-07-24 finding=finding-6 at=2026-07-24T20:54:11Z -->

# Cover registry-derived state-root variants

## Context

Parent PRD: `.prd-os/prds/prd-single-runtime-state-authority-2026-07-24.md`

## Acceptance

Write failing fixtures first for instance_q_dir, subtree fallback, null subtree, and missing explicit standalone state roots. Prove no writable path lands in a deletable generic directory.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Cover registry-derived state-root variants
