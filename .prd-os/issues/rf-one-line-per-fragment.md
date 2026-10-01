---
id: rf-one-line-per-fragment
title: A fragment must hold exactly one JSON record; empty or multi-line fragments are refused
status: open
priority: p1
parent_prd: prd-receipts-fragments-2026-10-01
allowed_files:
  - q-system/.q-system/scripts/receipts-ledger-check.py
  - q-system/.q-system/scripts/receipts_store.py
  - plugins/prd-os/scripts/receipts_store.py
  - plugins/kipi-dsse/scripts/receipts_store.py
  - q-system/.q-system/scripts/test/test-receipts-ledger-check.sh
  - q-system/.q-system/scripts/test/test-receipts-fragment-shape.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-receipts-fragment-shape.sh
  - bash q-system/.q-system/scripts/test/test-receipts-ledger-check.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-receipts-fragment-shape.sh"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-receipts-fragments-2026-10-01 finding=finding-10 at=2026-10-01T20:47:01Z -->

# A fragment must hold exactly one JSON record; empty or multi-line fragments are refused

## Context

Parent PRD: `.prd-os/prds/prd-receipts-fragments-2026-10-01.md`

## Acceptance

The ledger check refuses an empty fragment and a two-line fragment, naming the file.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] A fragment must hold exactly one JSON record; empty or multi-line fragments are refused
