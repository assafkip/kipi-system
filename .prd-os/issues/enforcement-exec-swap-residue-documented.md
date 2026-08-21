---
id: enforcement-exec-swap-residue-documented
title: Document that the basename ratchet refuses enforcer swaps, in the lint docstring and the rule text
status: open
priority: p1
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/.q-system/scripts/enforced-claim-lint.py
disallowed_files: []
required_checks:
  - grep -q 'ratchet' q-system/.q-system/scripts/enforced-claim-lint.py
required_reviews: []
bypass_check: "the docstring names the limitation rather than promising free rewording: grep -qi 'cannot be swapped' q-system/.q-system/scripts/enforced-claim-lint.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-6 at=2026-08-21T17:23:12Z -->

# Document that the basename ratchet refuses enforcer swaps, in the lint docstring and the rule text

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Document that the basename ratchet refuses enforcer swaps, in the lint docstring and the rule text
