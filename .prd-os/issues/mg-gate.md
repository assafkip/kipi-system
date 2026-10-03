---
id: mg-gate
title: model_gate module + model-gate.sh shell door (ASK-2393)
status: open
priority: p1
parent_prd: prd-model-gate-2026-10-02
allowed_files:
  - plugins/kipi-core/voiceloop/model_gate.py
  - plugins/kipi-core/voiceloop/tests/test_model_gate.py
  - plugins/kipi-core/voiceloop/tests/test_engine_surface.py
  - q-system/.q-system/scripts/model-gate.sh
disallowed_files: []
required_checks:
  - bash -c 'cd plugins/kipi-core && python3 -m pytest voiceloop/tests/test_model_gate.py -q'
required_reviews: []
bypass_check: "bash -c 'cd plugins/kipi-core && python3 -m pytest voiceloop/tests/test_model_gate.py -q -k round_cap_is_keyed'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-model-gate-2026-10-02 finding=finding-1 at=2026-10-02T06:19:39Z -->

# model_gate module + model-gate.sh shell door (ASK-2393)

## Context

Parent PRD: `.prd-os/prds/prd-model-gate-2026-10-02.md`

## Acceptance

A 4th call on one item is refused in enforce mode whatever the sha; unsettled calls are charged; one alert per job, limit and day; the door exits 75 and never runs the command on refusal.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] model_gate module + model-gate.sh shell door (ASK-2393)
