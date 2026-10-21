---
id: rf-reader-inventory
title: Every receipt reader reads monolith + fragments, and a repo-derived guard finds any new reader
status: open
priority: p1
parent_prd: prd-receipts-fragments-2026-10-01
allowed_files:
  - plugins/prd-os/scripts/judgment_compiler.py
  - plugins/prd-os/scripts/prd_runner.py
  - plugins/prd-os/scripts/receipts_store.py
  - plugins/kipi-dsse/scripts/receipts_store.py
  - plugins/kipi-dsse/scripts/test_receipt_finding_class.py
  - q-system/.q-system/scripts/accept-rate.py
  - q-system/.q-system/scripts/receipts_store.py
  - q-system/.q-system/scripts/test/test-updater-issue-sequence.py
  - q-system/.q-system/scripts/test/test-severity-floor.sh
  - q-system/.q-system/scripts/test/test-receipt-carry-approval.sh
  - q-system/.q-system/tests/separation/test_containment_sequence.py
  - q-system/.q-system/tests/separation/test_containment_claims.py
  - q-system/.q-system/tests/separation/test_updater_dependency_receipt.py
  - plugins/prd-os/tests/test_prd_runner.py
  - q-system/.q-system/tests/test_receipt_readers_inventory.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/tests/test_receipt_readers_inventory.py -q
required_reviews: []
bypass_check: "python3 -m pytest q-system/.q-system/tests/test_receipt_readers_inventory.py -q"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-receipts-fragments-2026-10-01 finding=finding-2 at=2026-10-01T20:47:01Z -->

# Every receipt reader reads monolith + fragments, and a repo-derived guard finds any new reader

## Context

Parent PRD: `.prd-os/prds/prd-receipts-fragments-2026-10-01.md`

## Acceptance

The inventory test greps the repo for receipts.jsonl / receipts_path and fails on any reader that does not go through a receipts_store helper; mutating one reader back to a raw open goes red.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Every receipt reader reads monolith + fragments, and a repo-derived guard finds any new reader
