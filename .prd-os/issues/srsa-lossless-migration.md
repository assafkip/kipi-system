---
id: srsa-lossless-migration
title: Migrate non-authoritative plugin data without loss
status: open
priority: p0
parent_prd: prd-single-runtime-state-authority-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/state_migration.py
  - plugins/kipi-core/kipi-mcp/tests/test_state_migration.py
disallowed_files:
  - q-system/canonical/**
  - q-system/my-project/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_state_migration.py
required_reviews:
  - data-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_state_migration.py -k 'conflict or interruption or rollback'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-single-runtime-state-authority-2026-07-24 finding=finding-4 at=2026-07-24T20:54:11Z -->

# Migrate non-authoritative plugin data without loss

## Context

Parent PRD: `.prd-os/prds/prd-single-runtime-state-authority-2026-07-24.md`

## Acceptance

Write failing conflict and interrupted-copy tests first. Map canonical, project, memory, output, bus, marketing, sources, profile, integrations, three databases, global voice, and AUDHD records; inventory hashes, stop on conflicts, verify copies, preserve the source, and emit a rollback receipt.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Migrate non-authoritative plugin data without loss
