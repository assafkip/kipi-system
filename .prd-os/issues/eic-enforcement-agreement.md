---
id: eic-enforcement-agreement
title: Compare documented enforcement with active configuration
status: open
priority: p1
parent_prd: prd-enforcement-instruction-contract-2026-07-24
allowed_files:
  - scripts/enforcement-agreement.py
  - tests/test_enforcement_agreement.py
  - CONTRIBUTE.md
  - UPDATE.md
disallowed_files:
  - lefthook.yml
  - .git/hooks/**
  - q-system/canonical/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_enforcement_agreement.py
required_reviews:
  - enforcement-owner
bypass_check: "python3 -m pytest -q tests/test_enforcement_agreement.py -k 'documented_only or active_only or prompt_only'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforcement-instruction-contract-2026-07-24 finding=finding-6 at=2026-07-24T21:10:19Z -->

# Compare documented enforcement with active configuration

## Context

Parent PRD: `.prd-os/prds/prd-enforcement-instruction-contract-2026-07-24.md`

## Acceptance

Write failing documented-only, active-only, and prompt-only fixtures first. Compare docs, Lefthook, settings, installed hooks, and executable scripts.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Compare documented enforcement with active configuration
