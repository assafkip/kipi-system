---
id: sag-quickfix-bounds
title: Quick-fix bounds encoded: test file itself or <=5-line fix in module under test; larger = quarantine + spillover
status: closed
priority: p1
parent_prd: prd-silent-absence-capability-gate-2026-07-23
allowed_files:
  - .prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md
  - q-system/.q-system/scripts/**
disallowed_files: []
required_checks:
  - sh -c 'grep -q "Quick-fix bounds" .prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md'
required_reviews: []
bypass_exempt: "scope-bounding text + per-issue allowed_files enforce it; no runtime surface to bypass"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-silent-absence-capability-gate-2026-07-23 finding=finding-11 at=2026-07-23T20:57:32Z -->

# Quick-fix bounds encoded: test file itself or <=5-line fix in module under test; larger = quarantine + spillover

## Context

Parent PRD: `.prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Quick-fix bounds encoded: test file itself or <=5-line fix in module under test; larger = quarantine + spillover
