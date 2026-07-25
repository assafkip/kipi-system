---
id: sdc-template-restoration
title: Restore exported canonical files to generic template form
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/canonical/discovery.md
  - q-system/canonical/pricing-framework.md
  - q-system/.q-system/tests/separation/test_template_restoration.py
disallowed_files:
  - instance-registry.json
  - kipi-update.sh
  - .git/**
  - /Users/assafkipnis/projects/intel/projects/kipi-investigations/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_template_restoration.py
required_reviews:
  - data-owner
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_template_restoration.py -k export_receipt"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=sdc-missing-template-restoration-owner at=2026-07-24T23:01:17Z -->

# Restore exported canonical files to generic template form

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write a failing instance-fact test first. Require the closed sdc-owner-export receipt before editing either source. Restore the existing documented sections with placeholders only, preserve both schemas, and prove no exported raw fact remains.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Restore exported canonical files to generic template form
