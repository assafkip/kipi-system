---
id: srsa-packaged-asset-manifest
title: Package and validate immutable runtime assets
status: open
priority: p0
parent_prd: prd-single-runtime-state-authority-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/pyproject.toml
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/assets-manifest.json
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/asset_loader.py
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/assets/**
  - plugins/kipi-core/kipi-mcp/sources/**
  - plugins/kipi-core/kipi-mcp/tests/test_installed_assets.py
disallowed_files:
  - q-system/canonical/**
  - q-system/my-project/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_assets.py
required_reviews:
  - packaging-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_assets.py -k missing_declared_asset"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-single-runtime-state-authority-2026-07-24 finding=finding-3 at=2026-07-24T20:54:11Z -->

# Package and validate immutable runtime assets

## Context

Parent PRD: `.prd-os/prds/prd-single-runtime-state-authority-2026-07-24.md`

## Acceptance

Write a failing installed-cache asset test first. Enumerate agents, templates, methodology, sources, and schedule templates and fail startup if any declared asset is absent.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Package and validate immutable runtime assets
