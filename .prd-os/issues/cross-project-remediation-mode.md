---
id: cross-project-remediation-mode
title: New --remediate mode: cross-project sweep over already-moved dirs, dry-first, .remediation.bak-backed, with a fixture unit test
status: closed
priority: p1
parent_prd: prd-reorg-stale-ref-remediation-2026-07-06
allowed_files:
  - scripts/persona-reorg.py
  - scripts/test_persona_reorg.py
disallowed_files: []
required_checks:
  - python3 scripts/test_persona_reorg.py
required_reviews: []
bypass_check: "python3 scripts/reorg-stale-ref-audit.py"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-reorg-stale-ref-remediation-2026-07-06 finding=finding-8 at=2026-07-06T22:35:44Z -->

# New --remediate mode: cross-project sweep over already-moved dirs, dry-first, .remediation.bak-backed, with a fixture unit test

## Context

Parent PRD: `.prd-os/prds/prd-reorg-stale-ref-remediation-2026-07-06.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] New --remediate mode: cross-project sweep over already-moved dirs, dry-first, .remediation.bak-backed, with a fixture unit test
