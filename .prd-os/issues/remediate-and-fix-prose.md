---
id: remediate-and-fix-prose
title: Run the remediation to 0 gating refs and fix operator-facing prose (kipi-investigations docs + current-state fan-out); leave dated records
status: in-progress
priority: p1
parent_prd: prd-reorg-stale-ref-remediation-2026-07-06
allowed_files:
  - scripts/reorg-stale-ref-audit.py
  - **/current-state.md
  - **/kipi-investigations/docs/*.md
disallowed_files: []
required_checks:
  - python3 scripts/reorg-stale-ref-audit.py
required_reviews: []
bypass_check: "python3 scripts/reorg-stale-ref-audit.py"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-reorg-stale-ref-remediation-2026-07-06 finding=finding-9 at=2026-07-06T22:35:44Z -->

# Run the remediation to 0 gating refs and fix operator-facing prose (kipi-investigations docs + current-state fan-out); leave dated records

## Context

Parent PRD: `.prd-os/prds/prd-reorg-stale-ref-remediation-2026-07-06.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Run the remediation to 0 gating refs and fix operator-facing prose (kipi-investigations docs + current-state fan-out); leave dated records
