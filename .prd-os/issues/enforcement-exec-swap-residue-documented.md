---
id: enforcement-exec-swap-residue-documented
title: Document that the basename ratchet refuses enforcer swaps, in the lint docstring and the rule text
status: closed
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
- [x] Document that the basename ratchet refuses enforcer swaps, in the lint docstring and the rule text

## Amendments

### 2026-08-21T19:19:49Z
Reason: Make the bypass_check case-insensitive (grep -q -> grep -qi). The docstring writes the phrase in caps for emphasis and the check was case-sensitive, so it failed on prose that satisfies its intent exactly. Rewording the docstring to match a grep is the antipattern the PRD template names outright: 'A check that shapes the code to fit the check is worse than no check.' Fixing the check is the correct direction.

Before:
- allowed_files: ['q-system/.q-system/scripts/enforced-claim-lint.py']
- required_checks: ["grep -q 'ratchet' q-system/.q-system/scripts/enforced-claim-lint.py"]
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/scripts/enforced-claim-lint.py']
- required_checks: ["grep -q 'ratchet' q-system/.q-system/scripts/enforced-claim-lint.py"]
- disallowed_files: []
