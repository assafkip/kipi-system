---
id: phase0-measure-script
title: Build phase0_measure.py with corrected kill-criterion verdict
status: closed
priority: p1
parent_prd: prd-prd-os-receipts-and-phase0-measure-2026-05-14
allowed_files:
  - plugins/prd-os/scripts/phase0_measure.py
  - plugins/prd-os/tests/test_phase0_measure.py
  - q-system/memory/working/prd-personas-baseline.md
disallowed_files: []
required_checks:
  - test -f plugins/prd-os/scripts/phase0_measure.py
  - pytest -q plugins/prd-os/tests/test_phase0_measure.py
required_reviews:
  - codex-review
---
<!-- generated-by: prd_split.py prd=prd-prd-os-receipts-and-phase0-measure-2026-05-14 finding=finding-4 at=2026-05-14T16:14:57Z -->

# Build phase0_measure.py with corrected kill-criterion verdict

## Context

Parent PRD: `.prd-os/prds/prd-prd-os-receipts-and-phase0-measure-2026-05-14.md`

## Acceptance

phase0_measure.py implements the corrected verdict logic: personas_applied.rate <= 0.5 * no_personas.rate => kill. Emits documented JSON schema. Appends one row to baseline.md per invocation.
