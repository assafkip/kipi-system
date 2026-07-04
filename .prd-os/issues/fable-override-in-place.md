---
id: fable-override-in-place
title: Every hard ban states its override condition and skip marker in the same paragraph
status: closed
priority: p1
parent_prd: prd-fable-discipline-2026-07-04
allowed_files:
  - plugins/prd-os/skills/**
  - plugins/prd-os/tests/**
disallowed_files: []
required_checks:
  - pytest -q plugins/prd-os/tests
  - bash plugins/prd-os/scripts/export-fable-mirror.sh --check
required_reviews: []
bypass_check: "pytest -q plugins/prd-os/tests"
---
<!-- generated-by: prd_split.py prd=prd-fable-discipline-2026-07-04 finding=finding-7 at=2026-07-04T01:45:32Z -->

# Every hard ban states its override condition and skip marker in the same paragraph

## Context

Parent PRD: `.prd-os/prds/prd-fable-discipline-2026-07-04.md`

## Acceptance

No ban without a documented escape hatch in the same paragraph. One marker per hook, no stacking (skill-hook-pairing.md). A test walks the skill text and fails on any ban paragraph lacking an override clause + marker.
