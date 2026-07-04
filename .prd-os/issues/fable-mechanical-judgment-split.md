---
id: fable-mechanical-judgment-split
title: Promote every mechanical checklist item into the lint hook; checklist becomes judgment-only
status: open
priority: p1
parent_prd: prd-fable-discipline-2026-07-04
allowed_files:
  - plugins/prd-os/skills/**
  - plugins/prd-os/hooks/**
  - plugins/prd-os/tests/**
disallowed_files: []
required_checks:
  - pytest -q plugins/prd-os/tests
  - bash plugins/prd-os/scripts/export-fable-mirror.sh --check
required_reviews: []
bypass_check: "pytest -q plugins/prd-os/tests"
---
<!-- generated-by: prd_split.py prd=prd-fable-discipline-2026-07-04 finding=finding-6 at=2026-07-04T01:45:32Z -->

# Promote every mechanical checklist item into the lint hook; checklist becomes judgment-only

## Context

Parent PRD: `.prd-os/prds/prd-fable-discipline-2026-07-04.md`

## Acceptance

Every checklist item tagged mechanical or judgment. Mechanical items exist as lint detectors and are absent from the checklist. Hook header enumerates detector coverage explicitly, including what it does NOT detect (hook-blind-spots scar).
