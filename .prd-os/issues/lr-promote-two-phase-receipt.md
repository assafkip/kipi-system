---
id: lr-promote-two-phase-receipt
title: The receipt is written in two phases around the copy, under one lock, so a crash leaves a pending row and never a silent copy
status: closed
priority: p1
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - kipi-promote.sh
  - kipi-push-upstream.sh
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
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'pending or crash or concurrent_promotions'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-11 at=2026-09-02T00:25:35Z -->

# The receipt is written in two phases around the copy, under one lock, so a crash leaves a pending row and never a silent copy

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first: a pending row is appended before the copy and a done row after the copied file re-hashes equal to the source, both under one flock on a sibling .lock of the receipt file; a copy that fails (destination made unwritable by the test) leaves exactly one pending row and no done row; the guard ignores pending rows; ten concurrent promotions of ten files leave twenty well-formed rows and ten copies.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] The receipt is written in two phases around the copy, under one lock, so a crash leaves a pending row and never a silent copy
