---
id: enforcement-whole-tree-gate
title: --all mode wired into lefthook pre-commit and validate-separation, plus both settings files
status: closed
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
- [x] --all mode wired into lefthook pre-commit and validate-separation, plus both settings files

## Amendments

### 2026-08-21T18:14:15Z
Reason: Add q-system/.q-system/enforced-claim-baseline.json to allowed_files. The whole-tree gate cannot go green without it: --all currently reports 32 uncovered markers across 29 rule files, and a gate red on its own population on day one is the unsatisfiable-population failure automated-filer-marking.md measured before shipping (8 files constructed issueCreate, 1 had the label). The baseline is shrink-only, so the debt is ratcheted rather than forgiven, and it lives OUTSIDE .claude/ deliberately because a JSON config the sanctioned path creates is create-once, correct-never (sp-fea73326).

Before:
- allowed_files: ['q-system/.q-system/scripts/enforced-claim-lint.py', 'q-system/.q-system/scripts/test_enforced_claim_lint.py', 'lefthook.yml', 'q-system/.q-system/proposals/*.json', 'plugins/kipi-core/scripts/validate-separation.py']
- required_checks: ['python3 q-system/.q-system/scripts/enforced-claim-lint.py --all', 'python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k whole_tree']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/scripts/enforced-claim-lint.py', 'q-system/.q-system/scripts/test_enforced_claim_lint.py', 'lefthook.yml', 'q-system/.q-system/proposals/*.json', 'plugins/kipi-core/scripts/validate-separation.py', 'q-system/.q-system/enforced-claim-baseline.json']
- required_checks: ['python3 q-system/.q-system/scripts/enforced-claim-lint.py --all', 'python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k whole_tree']
- disallowed_files: []

### 2026-08-21T18:17:22Z
Reason: Correct a wrong path in the PRD manifest I authored: validate-separation.py lives at the REPO ROOT, not plugins/kipi-core/scripts/. The manifest entry pointed at a file that does not exist, which would have made this issue's validator integration silently unbuildable. Recorded rather than worked around, because a spec naming a nonexistent path is the same class of unverified claim this PRD is about.

Before:
- allowed_files: ['q-system/.q-system/scripts/enforced-claim-lint.py', 'q-system/.q-system/scripts/test_enforced_claim_lint.py', 'lefthook.yml', 'q-system/.q-system/proposals/*.json', 'plugins/kipi-core/scripts/validate-separation.py', 'q-system/.q-system/enforced-claim-baseline.json']
- required_checks: ['python3 q-system/.q-system/scripts/enforced-claim-lint.py --all', 'python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k whole_tree']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/scripts/enforced-claim-lint.py', 'q-system/.q-system/scripts/test_enforced_claim_lint.py', 'lefthook.yml', 'q-system/.q-system/proposals/*.json', 'validate-separation.py', 'q-system/.q-system/enforced-claim-baseline.json']
- required_checks: ['python3 q-system/.q-system/scripts/enforced-claim-lint.py --all', 'python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k whole_tree']
- disallowed_files: []
