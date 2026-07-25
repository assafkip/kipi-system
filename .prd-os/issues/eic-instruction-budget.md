---
id: eic-instruction-budget
title: Reduce always-on instructions to 300 lines without losing protections
status: open
priority: p1
parent_prd: prd-enforcement-instruction-contract-2026-07-24
allowed_files:
  - AGENTS.md
  - CLAUDE.md
  - .claude/rules/**
  - q-system/.q-system/scripts/instruction-budget-audit.py
  - q-system/.q-system/scripts/test/test-instruction-protection-parity.sh
disallowed_files:
  - q-system/canonical/**
  - lefthook.yml
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 q-system/.q-system/scripts/instruction-budget-audit.py
  - bash q-system/.q-system/scripts/test/test-instruction-protection-parity.sh
required_reviews:
  - instruction-owner
  - enforcement-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-instruction-protection-parity.sh --assert-no-prompt-only-protection"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforcement-instruction-contract-2026-07-24 finding=finding-4 at=2026-07-24T21:10:19Z -->

# Reduce always-on instructions to 300 lines without losing protections

## Context

Parent PRD: `.prd-os/prds/prd-enforcement-instruction-contract-2026-07-24.md`

## Acceptance

Write a failing protection-parity fixture first. Reach 300 lines or fewer by scoping guidance while every executable protection remains represented and runnable.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Reduce always-on instructions to 300 lines without losing protections
