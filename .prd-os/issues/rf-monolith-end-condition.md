---
id: rf-monolith-end-condition
title: The monolith write exception has a stated end: the switch-over sha, after which only history reads it
status: open
priority: p1
parent_prd: prd-receipts-fragments-2026-10-01
allowed_files:
  - lefthook.yml
  - .gitignore
  - q-system/.q-system/scripts/receipts-ledger-check.py
  - q-system/.q-system/scripts/receipt-carry-approval.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-receipts-ledger-check.sh
required_reviews: []
bypass_check: "grep -nE 'SWITCHOVER_SHA|switch-over' q-system/.q-system/scripts/receipts-ledger-check.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-receipts-fragments-2026-10-01 finding=finding-7 at=2026-10-01T20:47:01Z -->

# The monolith write exception has a stated end: the switch-over sha, after which only history reads it

## Context

Parent PRD: `.prd-os/prds/prd-receipts-fragments-2026-10-01.md`

## Acceptance

Monolith lines dated before the switch-over sha stay valid history; a monolith append in a commit after it is refused.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] The monolith write exception has a stated end: the switch-over sha, after which only history reads it
