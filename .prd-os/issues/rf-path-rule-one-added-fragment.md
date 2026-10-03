---
id: rf-path-rule-one-added-fragment
title: Path rules accept exactly one ADDED fragment, anchored, regular file, no monolith change
status: open
priority: p1
parent_prd: prd-receipts-fragments-2026-10-01
allowed_files:
  - q-system/.q-system/scripts/converge.sh
  - q-system/.q-system/scripts/receipt-carry-approval.sh
  - q-system/.q-system/scripts/test/test-receipt-carry-approval.sh
  - q-system/.q-system/scripts/test/test-rf-path-rule-one-added-fragment.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-rf-path-rule-one-added-fragment.sh
  - bash q-system/.q-system/scripts/test/test-receipt-carry-approval.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-rf-path-rule-one-added-fragment.sh"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-receipts-fragments-2026-10-01 finding=finding-4 at=2026-10-01T20:47:01Z -->

# Path rules accept exactly one ADDED fragment, anchored, regular file, no monolith change

## Context

Parent PRD: `.prd-os/prds/prd-receipts-fragments-2026-10-01.md`

## Acceptance

The carry refuses a head that deletes or modifies a receipt, adds a nested path under receipts.d/, or touches the monolith; it allows exactly one added receipts.d/<name>.jsonl.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Path rules accept exactly one ADDED fragment, anchored, regular file, no monolith change
