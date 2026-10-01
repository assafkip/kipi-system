---
id: rf-origin-confirm-set
title: converge's origin confirm reads monolith + fragments at FETCH_HEAD through the same predicate as the local dedup
status: open
priority: p1
parent_prd: prd-receipts-fragments-2026-10-01
allowed_files:
  - q-system/.q-system/scripts/converge.sh
  - q-system/.q-system/scripts/test/test-converge-receipt-fragments.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-converge-receipt-fragments.sh
required_reviews: []
bypass_check: "! grep -nF 'show \"FETCH_HEAD:.prd-os/receipts.jsonl\"' q-system/.q-system/scripts/converge.sh"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-receipts-fragments-2026-10-01 finding=finding-6 at=2026-10-01T20:47:01Z -->

# converge's origin confirm reads monolith + fragments at FETCH_HEAD through the same predicate as the local dedup

## Context

Parent PRD: `.prd-os/prds/prd-receipts-fragments-2026-10-01.md`

## Acceptance

A receipt present on origin only as a fragment is CONFIRMED; one present only in the local tree is not.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] converge's origin confirm reads monolith + fragments at FETCH_HEAD through the same predicate as the local dedup
