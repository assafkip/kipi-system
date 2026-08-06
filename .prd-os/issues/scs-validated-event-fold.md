---
id: scs-validated-event-fold
title: Implement the validated latest-event fold
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - plugins/prd-os/scripts/spillover_events.py
  - plugins/prd-os/schemas/spillover-event.schema.json
  - plugins/prd-os/tests/test_spillover_events.py
  - plugins/prd-os/scripts/prd_runner.py
  - plugins/prd-os/scripts/findings_writer.py
  - plugins/prd-os/tests/test_findings_writer_body.py
disallowed_files:
  - .prd-os/spillover.jsonl
  - q-system/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py -k 'invalid or duplicate or timestamp'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-1 at=2026-07-24T21:14:34Z -->

# Implement the validated latest-event fold

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write failing invalid-JSON, invalid-transition, duplicate-ID, and out-of-order-timestamp tests first. Fold valid events by file order and fail closed with line evidence.

## Amendment 2026-08-06: prd_runner.py moved to allowed_files

The spec as split forbade `prd_runner.py`, which would have shipped
`spillover_events.py` as a module with no caller. `_read_spillover` is the ONE
function every reader of the ledger goes through (`gates run`, `spillover
check|list|triage|resolve|reclassify`), and its `except json.JSONDecodeError:
continue` IS the defect this issue exists to fix. Fixing it anywhere else leaves
the live path untouched, which is the inert-wiring scar this repo already has
(a gap-class checklist "wired" into an instance that the runtime never loaded).

Single chokepoint, not N call sites: the validator is called from
`_read_spillover` only. Nothing else reads the ledger file directly.

## Amendment 2 2026-08-06: findings_writer.py (the ledger's other writer)

This issue already took ownership of the WRITE path: `validate_for_append` now
gates `_spillover_append` (sp-940e1013). `findings_writer._sync_spillover_for_finding`
calls that same `_spillover_append`, and it feeds it a body truncated to 120
chars (line 470), so it is the one producer that writes a structurally valid but
INFORMATION-LOSSY event through the chokepoint this issue hardened.

Validating the shape of an event while its content is silently halved is a
half-finished job. Same file, same chokepoint, same defect class.

Recorded as a SECOND amendment rather than absorbed quietly: two amendments on
one issue is the point at which scope drift should be visible to a reviewer.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Implement the validated latest-event fold
