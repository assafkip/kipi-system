---
id: mg-route-run-model
title: voiceloop run_model asks the gate before any provider branch (ASK-2394)
status: open
priority: p1
parent_prd: prd-model-gate-2026-10-02
allowed_files:
  - plugins/kipi-core/voiceloop/prompt_render.py
  - plugins/kipi-core/voiceloop/tests/test_model_gate_route.py
disallowed_files: []
required_checks:
  - bash -c 'cd plugins/kipi-core && python3 -m pytest voiceloop/tests/test_model_gate_route.py voiceloop/tests/test_usage_ledger.py -q'
required_reviews: []
bypass_check: "bash -c 'cd plugins/kipi-core && python3 -m pytest voiceloop/tests/test_model_gate_route.py -q'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-model-gate-2026-10-02 finding=finding-2 at=2026-10-02T06:19:39Z -->

# voiceloop run_model asks the gate before any provider branch (ASK-2394)

## Context

Parent PRD: `.prd-os/prds/prd-model-gate-2026-10-02.md`

## Acceptance

A refused run_model call never starts the binary and returns None; the gate's spend for the job rises by the row the meter wrote.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] voiceloop run_model asks the gate before any provider branch (ASK-2394)
