---
id: ath-receipt-compaction
title: Bound completion-receipt storage and reads
status: open
priority: p1
parent_prd: prd-automation-terminal-health-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/job-receipt-store.py
  - q-system/.q-system/tests/test_job_receipt_compaction.py
disallowed_files:
  - q-system/output/**
  - instance-registry.json
  - .prd-os/**
  - /Users/assafkipnis/projects/cole-gtm/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_job_receipt_compaction.py
required_reviews:
  - automation-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_job_receipt_compaction.py -k boot_bound"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-automation-terminal-health-2026-07-24 finding=finding-7 at=2026-07-24T21:08:00Z -->

# Bound completion-receipt storage and reads

## Context

Parent PRD: `.prd-os/prds/prd-automation-terminal-health-2026-07-24.md`

## Acceptance

Write a failing 10,001-record boot test first. Compact before whole-file reads, verify archive counts and hashes, and bound the active log.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Bound completion-receipt storage and reads
