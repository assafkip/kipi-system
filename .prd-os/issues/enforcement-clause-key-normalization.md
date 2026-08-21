---
id: enforcement-clause-key-normalization
title: Exact clause-key normalization, duplicate keys rejected, orphan dispositions rejected
status: closed
priority: p0
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/.q-system/scripts/enforced-claim-lint.py
  - q-system/.q-system/scripts/test_enforced_claim_lint.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k clause_key
required_reviews: []
bypass_check: "normalization lives in exactly one function: grep -c 'def clause_key' q-system/.q-system/scripts/enforced-claim-lint.py | grep -qx 1"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-7 at=2026-08-21T17:23:12Z -->

# Exact clause-key normalization, duplicate keys rejected, orphan dispositions rejected

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Exact clause-key normalization, duplicate keys rejected, orphan dispositions rejected
