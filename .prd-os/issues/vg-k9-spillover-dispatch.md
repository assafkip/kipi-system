---
id: vg-k9-spillover-dispatch
title: A spillover ticket with a Definition of Ready and owner:sana is dispatch work, not a fleet alert
status: in-progress
priority: p1
parent_prd: standalone
allowed_files:
  - q-system/.q-system/scripts/linear-worker.sh
  - q-system/.q-system/scripts/test/test_spillover_dispatch.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__scripts__test__test_spillover_dispatch.py.json
disallowed_files: []
required_checks:
  - python3 -m pytest -q q-system/.q-system/scripts/test/test_spillover_dispatch.py q-system/.q-system/scripts/test/test_linear_alert_triage.py
required_reviews: []
bypass_exempt: "No gate is bypassed. The change widens what the fleet worker picks, so the red test pins both sides: a spillover ticket with a DoR and owner:sana is picked, and a bare alert or any other alert with a DoR is still refused."
deliverables_count: 4
---
<!-- generated-by: prd_split.py prd=standalone-ask-4410 finding=k9-spillover-dispatch at=2026-11-11T00:20:00Z -->
<!-- Standalone spec (ASK-4410, child of ASK-3815). Not split from the approved voicegate PRD; that PRD stays untouched. The marker only satisfies the runner's format check. -->

# A spillover ticket with a Definition of Ready and owner:sana is dispatch work, not a fleet alert

## Context

RULE-2026-11-09-B part 3 (consulting `decisions.md`): "a spillover ticket carrying a Definition of Ready and `owner:sana` is dispatch work, not an alert."

Spillover tickets are filed through the fleet-alert path by `spillover-linear-check.py`, so they carry the `kipi-alert-fingerprint` marker. `is_fleet_alert()` in `linear-worker.sh` then skips them in `ready()`, `ready_ignoring_project()` and the WIP walk, and only the nightly triage promotes them (about 60 a night against about 1,094 queued).

## Acceptance

- `is_fleet_alert()` returns false for an issue that carries the alert marker, the spillover form written by `spillover-linear-check.py:message_for`, a Definition of Ready, and the `owner:sana` label.
- The DoR test is the one `ready()` already uses (the text `Definition of Ready`), held in one constant. No second DoR parser.
- Narrow on purpose: an alert that is not a spillover ticket stays an alert even with a DoR. `test_linear_alert_triage.py::test_a_dor_alone_does_not_unblock_it` (ASK-839) pins that and must stay green.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Red first on origin/main: a fixture spillover ticket (marker, DoR, owner:sana, project kipi-system) is picked by `ready()`; shown failing before the change
- [x] The same spillover ticket without a DoR, without owner:sana, and a non-spillover alert with a DoR are each refused (negative self-tests)
- [x] `is_fleet_alert()` carries the exemption, with the DoR text in one constant shared with the existing check
- [x] `test_linear_alert_triage.py` stays green with no edit
