---
id: enforcement-directive-count-ratchet
title: Directive-count ratchet so a new normative line cannot inherit an existing disposition
status: closed
priority: p0
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/.q-system/scripts/enforced-claim-lint.py
  - q-system/.q-system/scripts/test_enforced_claim_lint.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k directive
required_reviews: []
bypass_check: "exactly one directive-counting function exists: grep -c 'def count_directives' q-system/.q-system/scripts/enforced-claim-lint.py | grep -qx 1"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-3 at=2026-08-21T17:23:12Z -->

# Directive-count ratchet so a new normative line cannot inherit an existing disposition

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Directive-count ratchet so a new normative line cannot inherit an existing disposition
