---
id: eic-lefthook-install
title: Make Lefthook the deterministic fresh-clone installer
status: open
priority: p1
parent_prd: prd-enforcement-instruction-contract-2026-07-24
allowed_files:
  - scripts/install-hooks
  - lefthook.yml
  - tests/test_hook_install.py
disallowed_files:
  - .git/hooks/**
  - .githooks/**
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_hook_install.py
required_reviews:
  - enforcement-owner
bypass_check: "python3 -m pytest -q tests/test_hook_install.py -k 'fresh_clone or conflicting'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforcement-instruction-contract-2026-07-24 finding=finding-1 at=2026-07-24T21:10:19Z -->

# Make Lefthook the deterministic fresh-clone installer

## Context

Parent PRD: `.prd-os/prds/prd-enforcement-instruction-contract-2026-07-24.md`

## Acceptance

Write failing fresh-clone and conflicting-hooksPath tests first. Install and verify Lefthook pre-commit and pre-push without editing global Git config.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Make Lefthook the deterministic fresh-clone installer
