---
id: sag-quarantine-expiry
title: Quarantine entries require reason + spillover_id + expires; expired = RED; count always printed
status: closed
priority: p1
parent_prd: prd-silent-absence-capability-gate-2026-07-23
allowed_files:
  - q-system/.q-system/scripts/capability-gate.py
  - q-system/.q-system/capability-manifest.json
  - q-system/.q-system/scripts/test_capability_gate.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test_capability_gate.py --only quarantine
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/capability-gate.py --check-only"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-silent-absence-capability-gate-2026-07-23 finding=finding-6 at=2026-07-23T20:57:32Z -->

# Quarantine entries require reason + spillover_id + expires; expired = RED; count always printed

## Context

Parent PRD: `.prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Quarantine entries require reason + spillover_id + expires; expired = RED; count always printed
