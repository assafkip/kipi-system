---
id: srsa-production-asset-loader
title: Wire the packaged asset manifest into production startup
status: open
priority: p0
parent_prd: prd-single-runtime-state-authority-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/asset_loader.py
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py
  - plugins/kipi-core/kipi-mcp/tests/test_asset_startup.py
disallowed_files:
  - q-system/**
  - instance-registry.json
  - .prd-os/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_asset_startup.py
required_reviews:
  - packaging-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_asset_startup.py -k missing_or_external"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-single-runtime-state-authority-2026-07-24 finding=finding-8 at=2026-07-24T20:54:11Z -->

# Wire the packaged asset manifest into production startup

## Context

Parent PRD: `.prd-os/prds/prd-single-runtime-state-authority-2026-07-24.md`

## Acceptance

Write a failing startup test first. Production startup must load the manifest, verify every packaged asset, and refuse missing or cache-external resources.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Wire the packaged asset manifest into production startup
