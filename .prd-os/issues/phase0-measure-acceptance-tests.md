---
id: phase0-measure-acceptance-tests
title: Strengthen Issue 2 tests: JSON schema, baseline append, sample verdicts
status: closed
priority: p2
parent_prd: prd-prd-os-receipts-and-phase0-measure-2026-05-14
allowed_files:
  - plugins/prd-os/tests/test_phase0_measure.py
disallowed_files: []
required_checks:
  - pytest -q plugins/prd-os/tests/test_phase0_measure.py
required_reviews: []
---
<!-- generated-by: prd_split.py prd=prd-prd-os-receipts-and-phase0-measure-2026-05-14 finding=finding-5 at=2026-05-14T16:14:57Z -->

# Strengthen Issue 2 tests: JSON schema, baseline append, sample verdicts

## Context

Parent PRD: `.prd-os/prds/prd-prd-os-receipts-and-phase0-measure-2026-05-14.md`

## Acceptance

Tests assert: stdout is parseable JSON with documented schema; baseline.md has exactly one new row after invocation; verdict computation is correct for synthetic kill / continue / insufficient-data cases.
