---
id: srsa-unified-readers
title: Route MCP, morning, backup, import, export, and validation through one resolver
status: open
priority: p0
parent_prd: prd-single-runtime-state-authority-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/morning_init.py
  - plugins/kipi-core/kipi-mcp/tests/test_state_authority.py
disallowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_state_authority.py
required_reviews:
  - runtime-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_state_authority.py -k two_brain"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-single-runtime-state-authority-2026-07-24 finding=finding-2 at=2026-07-24T20:54:11Z -->

# Route MCP, morning, backup, import, export, and validation through one resolver

## Context

Parent PRD: `.prd-os/prds/prd-single-runtime-state-authority-2026-07-24.md`

## Acceptance

Write a failing shared-record contract test first. Every listed reader and writer must report and use the same resolved store, with no direct legacy repository read.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Route MCP, morning, backup, import, export, and validation through one resolver
