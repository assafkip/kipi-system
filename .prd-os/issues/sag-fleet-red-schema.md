---
id: sag-fleet-red-schema
title: No instance-level acceptable-red: statuses are green/red/skipped(standalone) only; reasons exist per-test (quarantine), never per-instance
status: closed
priority: p1
parent_prd: prd-silent-absence-capability-gate-2026-07-23
allowed_files:
  - fleet-capability-verify.py
disallowed_files: []
required_checks:
  - python3 fleet-capability-verify.py --self-test
required_reviews: []
bypass_exempt: "schema-definition slice of sag-fleet-verify-semantics; same self-test covers it"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-silent-absence-capability-gate-2026-07-23 finding=finding-16 at=2026-07-23T20:57:32Z -->

# No instance-level acceptable-red: statuses are green/red/skipped(standalone) only; reasons exist per-test (quarantine), never per-instance

## Context

Parent PRD: `.prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] No instance-level acceptable-red: statuses are green/red/skipped(standalone) only; reasons exist per-test (quarantine), never per-instance
