---
id: lr-promotion-candidates-status
title: kipi promote --candidates lists every divergent lesson in a hub instance with its receipt status; --void records a voided row
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
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'candidates or voided'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-4 at=2026-09-02T00:25:35Z -->

# kipi promote --candidates lists every divergent lesson in a hub instance with its receipt status; --void records a voided row

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first: --candidates [--instance NAME] resolves the instance through the registry, lists each lessons/*.md present there and absent-or-divergent in the skeleton with status none, pending, done or voided and the exact next command per file; --void PATH --reason TEXT appends a voided row, and the guard still refuses to push a voided divergent lesson (the listed action is a move to the instance's own lessons dir); run read-only against the live consulting checkout at closeout, the eight lessons appear with status none and that output is the closeout evidence. No live promotion.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] kipi promote --candidates lists every divergent lesson in a hub instance with its receipt status; --void records a voided row
