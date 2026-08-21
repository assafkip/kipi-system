---
id: enforcement-exec-path-not-basename
title: exec is a repo-relative path with one referent, never a basename
status: open
priority: p0
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/.q-system/scripts/enforced-claim-lint.py
  - q-system/.q-system/scripts/test_enforced_claim_lint.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k exec_path
required_reviews: []
bypass_check: "a bare basename in exec is rejected rather than resolved: the exec_path mutation exits 2"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-9 at=2026-08-21T17:23:12Z -->

# exec is a repo-relative path with one referent, never a basename

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] exec is a repo-relative path with one referent, never a basename
