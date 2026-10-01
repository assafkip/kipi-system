---
id: rf-locate-pr-receipt-gate
title: Locate the PR receipt gate (LEDGER_PREFIX / pr-receipt-gate.py) and accept fragments there, or remove the stale citations
status: open
priority: p1
parent_prd: prd-receipts-fragments-2026-10-01
allowed_files:
  - q-system/.q-system/scripts/converge.sh
  - q-system/.q-system/scripts/receipt-carry-approval.sh
  - plugins/prd-os/scripts/prd_split.py
  - q-system/.q-system/scripts/test/fixtures/silent-success/GREEN-checked-swallow.converge.sh
  - q-system/.q-system/scripts/test/test-receipt-gate-admits-fragment.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-receipt-gate-admits-fragment.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-receipt-gate-admits-fragment.sh"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-receipts-fragments-2026-10-01 finding=finding-9 at=2026-10-01T20:47:01Z -->

# Locate the PR receipt gate (LEDGER_PREFIX / pr-receipt-gate.py) and accept fragments there, or remove the stale citations

## Context

Parent PRD: `.prd-os/prds/prd-receipts-fragments-2026-10-01.md`

## Acceptance

Either the live gate is found and admits a fragment receipt (proved on a test PR), or every citation of it is removed with the measurement that it no longer exists. This issue runs FIRST: a live gate that admits only the monolith would block every merge.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Locate the PR receipt gate (LEDGER_PREFIX / pr-receipt-gate.py) and accept fragments there, or remove the stale citations
