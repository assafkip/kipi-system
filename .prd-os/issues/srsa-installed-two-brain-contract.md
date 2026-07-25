---
id: srsa-installed-two-brain-contract
title: Run installed-cache and two-brain negative contracts
status: open
priority: p0
parent_prd: prd-single-runtime-state-authority-2026-07-24
allowed_files:
  - plugins/kipi-core/kipi-mcp/tests/test_installed_state_contract.py
  - plugins/kipi-core/kipi-mcp/tests/fixtures/installed-cache/**
disallowed_files:
  - plugins/kipi-core/kipi-mcp/src/**
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_state_contract.py
required_reviews:
  - test-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_installed_state_contract.py -k rejects_two_brain"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-single-runtime-state-authority-2026-07-24 finding=finding-5 at=2026-07-24T20:54:11Z -->

# Run installed-cache and two-brain negative contracts

## Context

Parent PRD: `.prd-os/prds/prd-single-runtime-state-authority-2026-07-24.md`

## Acceptance

Write the failing installed-layout reproducer first. Prove commands and MCP share one root and reject mismatched stores before a write.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Run installed-cache and two-brain negative contracts
