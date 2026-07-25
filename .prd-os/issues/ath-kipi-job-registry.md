---
id: ath-kipi-job-registry
title: Enumerate every Kipi-owned scheduled job
status: open
priority: p1
parent_prd: prd-automation-terminal-health-2026-07-24
allowed_files:
  - q-system/.q-system/config/kipi-jobs.json
  - q-system/.q-system/tests/test_kipi_job_registry.py
disallowed_files:
  - q-system/output/**
  - instance-registry.json
  - .prd-os/**
  - /Users/assafkipnis/projects/cole-gtm/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_kipi_job_registry.py
required_reviews:
  - automation-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_kipi_job_registry.py -k unclassified"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-automation-terminal-health-2026-07-24 finding=finding-6 at=2026-07-24T21:08:00Z -->

# Enumerate every Kipi-owned scheduled job

## Context

Parent PRD: `.prd-os/prds/prd-automation-terminal-health-2026-07-24.md`

## Acceptance

Write a failing unclassified-label test first. Enumerate labels, adapters, installers, dependencies, receipt paths, and terminal invariants for every Kipi-owned job.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Enumerate every Kipi-owned scheduled job
