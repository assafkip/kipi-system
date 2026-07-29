---
id: dr-fleet-wiring-hold-release-2026-07-28
title: Ship the gates that are proven safe, hold the one that is not, with the hold enforced
status: closed
priority: p0
parent_prd: prd-deterministic-reading-2026-07-28
allowed_files:
  - settings-template.json
  - q-system/.q-system/scripts/settings-template-sync-check.py
  - q-system/.q-system/scripts/read-first-gate.py
  - q-system/.q-system/scripts/test_read_first_gate.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/settings-template-sync-check.py --check
  - python3 q-system/.q-system/scripts/test_read_first_gate.py
required_reviews: []
bypass_check: "test \"$(grep -c 'read-first-gate' settings-template.json)\" -eq 0 && grep -q 'read-first-gate.py' q-system/.q-system/scripts/settings-template-sync-check.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-deterministic-reading-2026-07-28 finding=finding-25 at=2026-07-28T22:58:38Z -->

# Ship the gates that are proven safe, hold the one that is not, with the hold enforced

## Context

Parent PRD: `.prd-os/prds/prd-deterministic-reading-2026-07-28.md`

## Acceptance

handoff-provenance-lint and client-output-evidence-gate are wired fleet-wide and their SKELETON_ONLY entries removed; read-first-gate stays out of the template with a measured reason, and sync-check goes RED if that hold is silently dropped. ASK-229, ASK-235.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Ship the gates that are proven safe, hold the one that is not, with the hold enforced
