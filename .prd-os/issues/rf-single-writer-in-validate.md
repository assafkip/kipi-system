---
id: rf-single-writer-in-validate
title: The monolith-append refusal runs in validate against a named switch-over sha, not only in lefthook
status: open
priority: p1
parent_prd: prd-receipts-fragments-2026-10-01
allowed_files:
  - .github/workflows/validate.yml
  - q-system/.q-system/scripts/receipts-ledger-check.py
  - q-system/.q-system/scripts/test/test-receipts-ledger-check.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-receipts-ledger-check.sh
required_reviews: []
bypass_check: "grep -nF 'receipts-ledger-check.py' .github/workflows/validate.yml"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-receipts-fragments-2026-10-01 finding=finding-3 at=2026-10-01T20:47:01Z -->

# The monolith-append refusal runs in validate against a named switch-over sha, not only in lefthook

## Context

Parent PRD: `.prd-os/prds/prd-receipts-fragments-2026-10-01.md`

## Acceptance

A PR that appends a line to .prd-os/receipts.jsonl after the switch-over sha fails validate with the line named.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] The monolith-append refusal runs in validate against a named switch-over sha, not only in lefthook
