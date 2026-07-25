---
id: srsa-authoritative-path-contract
title: Implement the authoritative instance and fleet path contract
status: open
priority: p0
parent_prd: prd-single-runtime-state-authority-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py
  - plugins/kipi-core/kipi-mcp/tests/test_paths.py
disallowed_files:
  - q-system/canonical/**
  - q-system/my-project/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py
required_reviews:
  - runtime-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py -k 'ambiguous or plugin_cache_write'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-single-runtime-state-authority-2026-07-24 finding=finding-1 at=2026-07-24T20:54:11Z -->

# Implement the authoritative instance and fleet path contract

## Context

Parent PRD: `.prd-os/prds/prd-single-runtime-state-authority-2026-07-24.md`

## Acceptance

Write failing root-resolution and ambiguity tests first. Derive each instance state root from registry path, subtree_prefix, and instance_q_dir, require an explicit standalone mapping, and resolve fleet registry only from KIPI_FLEET_ROOT.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Implement the authoritative instance and fleet path contract
