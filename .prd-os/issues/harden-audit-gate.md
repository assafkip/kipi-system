---
id: harden-audit-gate
title: Harden reorg-stale-ref-audit.py: single-source map, new-path existence, ${HOME} form, wider gating set, docstring (consolidates findings 2/4/5/10)
status: closed
priority: p1
parent_prd: prd-reorg-stale-ref-remediation-2026-07-06
allowed_files:
  - scripts/reorg-stale-ref-audit.py
  - scripts/persona-reorg.py
disallowed_files: []
required_checks:
  - python3 scripts/reorg-stale-ref-audit.py
required_reviews: []
bypass_check: "python3 scripts/reorg-stale-ref-audit.py"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-reorg-stale-ref-remediation-2026-07-06 finding=finding-6 at=2026-07-06T22:35:44Z -->

# Harden reorg-stale-ref-audit.py: single-source map, new-path existence, ${HOME} form, wider gating set, docstring (consolidates findings 2/4/5/10)

## Context

Parent PRD: `.prd-os/prds/prd-reorg-stale-ref-remediation-2026-07-06.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Harden reorg-stale-ref-audit.py: single-source map, new-path existence, ${HOME} form, wider gating set, docstring (consolidates findings 2/4/5/10)
