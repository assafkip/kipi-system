---
id: enforcement-whole-tree-gate
title: --all mode wired into lefthook pre-commit and validate-separation, plus both settings files
status: open
priority: p0
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/.q-system/scripts/enforced-claim-lint.py
  - q-system/.q-system/scripts/test_enforced_claim_lint.py
  - lefthook.yml
  - q-system/.q-system/proposals/*.json
  - validate-separation.py
  - q-system/.q-system/enforced-claim-baseline.json
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/enforced-claim-lint.py --all
  - python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k whole_tree
required_reviews: []
bypass_check: "the lint is reachable outside PostToolUse: lefthook.yml references enforced-claim-lint and the hook is present in both settings files"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-10 at=2026-08-21T17:23:12Z -->

# --all mode wired into lefthook pre-commit and validate-separation, plus both settings files

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] --all mode wired into lefthook pre-commit and validate-separation, plus both settings files
