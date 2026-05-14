---
id: phase0-baseline-doc-scope
title: Update prd-personas-baseline.md format to support measurement-row appends
status: closed
priority: p2
parent_prd: prd-prd-os-receipts-and-phase0-measure-2026-05-14
allowed_files:
  - q-system/memory/working/prd-personas-baseline.md
disallowed_files: []
required_checks:
  - grep -q 'measurement' q-system/memory/working/prd-personas-baseline.md
required_reviews: []
---
<!-- generated-by: prd_split.py prd=prd-prd-os-receipts-and-phase0-measure-2026-05-14 finding=finding-2 at=2026-05-14T16:14:57Z -->

# Update prd-personas-baseline.md format to support measurement-row appends

## Context

Parent PRD: `.prd-os/prds/prd-prd-os-receipts-and-phase0-measure-2026-05-14.md`

## Acceptance

Baseline doc extended with section documenting the row format phase0_measure.py will append. Existing rows preserved. Doc notes phase0_measure.py is the only writer going forward.
