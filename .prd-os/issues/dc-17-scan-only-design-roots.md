---
id: dc-17-scan-only-design-roots
title: The post-Bash scan walks only roots that hold a design-chain.json
status: open
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_scan_scope.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_scan_scope.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_scan_scope.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-15 at=2026-09-18T20:21:26Z -->

# The post-Bash scan walks only roots that hold a design-chain.json

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

scan_roots() drops any registered instance root with no design-chain.json and prunes nested worktrees (.wt-*, .claude/worktrees). Test builds a fake registry with one design root and one large non-design root and asserts the second is never walked.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] The post-Bash scan walks only roots that hold a design-chain.json
