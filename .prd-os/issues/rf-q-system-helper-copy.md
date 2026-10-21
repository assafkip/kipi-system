---
id: rf-q-system-helper-copy
title: q-system gets its own receipts_store helper, drift-pinned to the plugin copies; converge's inline Python uses it
status: open
priority: p1
parent_prd: prd-receipts-fragments-2026-10-01
allowed_files:
  - q-system/.q-system/scripts/receipts_store.py
  - plugins/prd-os/scripts/receipts_store.py
  - plugins/kipi-dsse/scripts/receipts_store.py
  - q-system/.q-system/scripts/converge.sh
  - q-system/.q-system/tests/test_receipts_store_copies.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/tests/test_receipts_store_copies.py -q
required_reviews: []
bypass_check: "python3 -m pytest q-system/.q-system/tests/test_receipts_store_copies.py -q"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-receipts-fragments-2026-10-01 finding=finding-5 at=2026-10-01T20:47:01Z -->

# q-system gets its own receipts_store helper, drift-pinned to the plugin copies; converge's inline Python uses it

## Context

Parent PRD: `.prd-os/prds/prd-receipts-fragments-2026-10-01.md`

## Acceptance

The three helper copies are byte-identical; editing one turns the test red.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] q-system gets its own receipts_store helper, drift-pinned to the plugin copies; converge's inline Python uses it
