---
id: phase0-layout-coupling-note
title: Document persona-detector PRD-layout coupling in phase0_measure.py docstring
status: closed
priority: p3
parent_prd: prd-prd-os-receipts-and-phase0-measure-2026-05-14
allowed_files:
  - plugins/prd-os/scripts/phase0_measure.py
disallowed_files: []
required_checks:
  - grep -q 'Persona Review' plugins/prd-os/scripts/phase0_measure.py
  - grep -q 'Skeptic' plugins/prd-os/scripts/phase0_measure.py
required_reviews: []
---
<!-- generated-by: prd_split.py prd=prd-prd-os-receipts-and-phase0-measure-2026-05-14 finding=finding-6 at=2026-05-14T16:14:57Z -->

# Document persona-detector PRD-layout coupling in phase0_measure.py docstring

## Context

Parent PRD: `.prd-os/prds/prd-prd-os-receipts-and-phase0-measure-2026-05-14.md`

## Acceptance

Module docstring names the layout coupling (## Persona Review, ### Skeptic, A1/A2/A3 conventions) and points to plugins/prd-os/templates/prd.md as the paired source of truth.
