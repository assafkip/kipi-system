---
id: ath-terminal-receipt-contract
title: Define terminal-output receipts for Kipi-owned jobs
status: open
priority: p1
parent_prd: prd-automation-terminal-health-2026-07-24
allowed_files:
  - q-system/.q-system/schemas/job-completion-receipt.schema.json
  - q-system/.q-system/tests/test_job_completion_receipts.py
disallowed_files:
  - q-system/output/**
  - instance-registry.json
  - .prd-os/**
  - /Users/assafkipnis/projects/cole-gtm/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_job_completion_receipts.py
required_reviews:
  - automation-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_job_completion_receipts.py -k 'missing or duplicate or nonterminal'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-automation-terminal-health-2026-07-24 finding=finding-1 at=2026-07-24T21:08:00Z -->

# Define terminal-output receipts for Kipi-owned jobs

## Context

Parent PRD: `.prd-os/prds/prd-automation-terminal-health-2026-07-24.md`

## Acceptance

Write failing missing, duplicate, and nonterminal receipt tests first. Require exactly one delivered, no-work, blocked, or failed terminal state with output and dependency evidence.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Define terminal-output receipts for Kipi-owned jobs
