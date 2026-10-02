---
id: mg-door-scan
title: Daily fleet scanner for model call sites not behind the gate (ASK-2395)
status: open
priority: p1
parent_prd: prd-model-gate-2026-10-02
allowed_files:
  - q-system/.q-system/scripts/fleet-model-gate-scan.py
  - q-system/.q-system/scripts/com.kipi.fleet-model-gate-scan.plist
  - q-system/.q-system/tests/test_fleet_model_gate_scan.py
  - AUTONOMOUS-SYSTEMS.md
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/tests/test_fleet_model_gate_scan.py -q
required_reviews: []
bypass_check: "python3 -m pytest q-system/.q-system/tests/test_fleet_model_gate_scan.py -q"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-model-gate-2026-10-02 finding=finding-6 at=2026-10-02T06:19:39Z -->

# Daily fleet scanner for model call sites not behind the gate (ASK-2395)

## Context

Parent PRD: `.prd-os/prds/prd-model-gate-2026-10-02.md`

## Acceptance

A checkout with a direct claude -p site is reported ungated and alerts once; the same site behind model-gate.sh is not; blind spots print as unscanned.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Daily fleet scanner for model call sites not behind the gate (ASK-2395)
