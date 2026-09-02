---
id: lr-promote-receipt-location
title: Receipts live in the skeleton at q-system/.q-system/promotions.receipts and the guard reads them from FETCH_HEAD, never from the instance working tree
status: closed
priority: p1
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - kipi-promote.sh
  - kipi-push-upstream.sh
  - q-system/.q-system/promotions.receipts
  - q-system/.q-system/tests/test_promotion_receipt.py
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - kipi-update.sh
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'fetch_head or local_receipt_ignored'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-12 at=2026-09-02T00:25:35Z -->

# Receipts live in the skeleton at q-system/.q-system/promotions.receipts and the guard reads them from FETCH_HEAD, never from the instance working tree

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first: kipi-promote.sh appends to <skeleton>/q-system/.q-system/promotions.receipts (an empty tracked file ships in this issue so the fan-out carries it); the guard reads the receipts with git show FETCH_HEAD:q-system/.q-system/promotions.receipts and a receipt row present only in the instance's working tree or HEAD does not pass a divergent lesson; KIPI_PROMOTIONS_FILE is honoured only when PYTEST_CURRENT_TEST is set and refused with a message otherwise; kipi update's fan-out list is confirmed to carry the file (a test greps kipi-update.sh's include rules, no live update).

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Receipts live in the skeleton at q-system/.q-system/promotions.receipts and the guard reads them from FETCH_HEAD, never from the instance working tree

## Amendments

### 2026-09-02T02:50:19Z
Reason: The root .gitignore ignores *.jsonl and instances copy that file at creation (consulting ignores it too; the updater never syncs ignore rules), so q-system/.q-system/promotions.jsonl would stay untracked in every instance and the guard's receipts integrity check would refuse every push after the first receipt. Renamed to q-system/.q-system/promotions.receipts, a name no ignore rule matches; allowed_files updated.

Before:
- allowed_files: ['kipi-promote.sh', 'kipi-push-upstream.sh', 'q-system/.q-system/promotions.jsonl', 'q-system/.q-system/tests/test_promotion_receipt.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**', 'kipi-update.sh']

After:
- allowed_files: ['kipi-promote.sh', 'kipi-push-upstream.sh', 'q-system/.q-system/promotions.receipts', 'q-system/.q-system/tests/test_promotion_receipt.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**', 'kipi-update.sh']
