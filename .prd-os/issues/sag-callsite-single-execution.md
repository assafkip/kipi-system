---
id: sag-callsite-single-execution
title: CI executes the gate exactly once: validate.yml owns the direct invocation; validate-separation gate section is skippable via env for CI
status: open
priority: p1
parent_prd: prd-silent-absence-capability-gate-2026-07-23
allowed_files:
  - .github/workflows/validate.yml
  - validate-separation.py
  - q-system/.q-system/scripts/test_capability_gate.py
disallowed_files: []
required_checks:
  - sh -c 'grep -c capability-gate .github/workflows/validate.yml'
required_reviews: []
bypass_check: "sh -c 'grep -q capability-gate .github/workflows/validate.yml'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-silent-absence-capability-gate-2026-07-23 finding=finding-15 at=2026-07-23T20:57:32Z -->

# CI executes the gate exactly once: validate.yml owns the direct invocation; validate-separation gate section is skippable via env for CI

## Context

Parent PRD: `.prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] CI executes the gate exactly once: validate.yml owns the direct invocation; validate-separation gate section is skippable via env for CI
