---
id: cwc-decision-reconciliation
title: Reconcile RULE-A through RULE-E with the decision authority
status: open
priority: p1
parent_prd: prd-canonical-writeback-contract-2026-07-24
allowed_files:
  - q-system/canonical/decisions.md
  - q-system/.q-system/tests/test_decision_agreement.py
disallowed_files:
  - q-system/canonical/autonomous-systems-record-2026-06-30.md
  - plugins/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_decision_agreement.py
required_reviews:
  - decision-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_decision_agreement.py -k missing_or_conflicting"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-writeback-contract-2026-07-24 finding=finding-3 at=2026-07-24T21:05:26Z -->

# Reconcile RULE-A through RULE-E with the decision authority

## Context

Parent PRD: `.prd-os/prds/prd-canonical-writeback-contract-2026-07-24.md`

## Acceptance

Write the failing RULE-A through RULE-E agreement test first. Add only source-evidenced decisions and stop on semantic conflicts.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Reconcile RULE-A through RULE-E with the decision authority
