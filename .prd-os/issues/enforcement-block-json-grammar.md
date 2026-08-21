---
id: enforcement-block-json-grammar
title: Disposition block is a fenced JSON array with a defined schema and a rejecting parser
status: open
priority: p0
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/.q-system/scripts/enforced-claim-lint.py
  - q-system/.q-system/scripts/test_enforced_claim_lint.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k grammar
required_reviews: []
bypass_check: "grep -c 'def parse_block' q-system/.q-system/scripts/enforced-claim-lint.py | grep -qx 1"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-2 at=2026-08-21T17:23:12Z -->

# Disposition block is a fenced JSON array with a defined schema and a rejecting parser

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Disposition block is a fenced JSON array with a defined schema and a rejecting parser
