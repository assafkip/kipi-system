---
id: sag-callsite-instance-check
title: Instance-side call site designed end-to-end: kipi check runs gate in the TARGET repo + kipi update runs gate per instance post-sync
status: open
priority: p0
parent_prd: prd-silent-absence-capability-gate-2026-07-23
allowed_files:
  - validate-separation.py
  - kipi-update.sh
  - kipi
  - q-system/.q-system/scripts/capability-gate.py
  - q-system/.q-system/scripts/test_capability_gate.py
disallowed_files: []
required_checks:
  - sh -c 'grep -q capability-gate validate-separation.py'
  - sh -c 'grep -q capability-gate kipi-update.sh'
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/capability-gate.py --check-only"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-silent-absence-capability-gate-2026-07-23 finding=finding-2 at=2026-07-23T20:57:32Z -->

# Instance-side call site designed end-to-end: kipi check runs gate in the TARGET repo + kipi update runs gate per instance post-sync

## Context

Parent PRD: `.prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Instance-side call site designed end-to-end: kipi check runs gate in the TARGET repo + kipi update runs gate per instance post-sync
