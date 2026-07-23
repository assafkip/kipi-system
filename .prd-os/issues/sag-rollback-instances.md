---
id: sag-rollback-instances
title: Rollback covers propagated instances: revert skeleton + re-run kipi update restores synced trees; no instance-local artifacts created
status: open
priority: p1
parent_prd: prd-silent-absence-capability-gate-2026-07-23
allowed_files:
  - .prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md
disallowed_files: []
required_checks:
  - sh -c 'grep -q "Instance rollback" .prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md'
required_reviews: []
bypass_exempt: "rollback procedure documentation; enforcement is the kipi update rsync itself"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-silent-absence-capability-gate-2026-07-23 finding=finding-12 at=2026-07-23T20:57:32Z -->

# Rollback covers propagated instances: revert skeleton + re-run kipi update restores synced trees; no instance-local artifacts created

## Context

Parent PRD: `.prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Rollback covers propagated instances: revert skeleton + re-run kipi update restores synced trees; no instance-local artifacts created
