---
id: scs-validated-event-fold
title: Implement the validated latest-event fold
status: closed
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
  - python3 -m pytest -q plugins/prd-os/tests/test_findings_writer_body.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py plugins/prd-os/tests/test_findings_writer_body.py"
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

## Amendment 3 2026-08-06: required_checks was missing a shipped test

Amendment 2 added `test_findings_writer_body.py` to allowed_files and NOT to
required_checks, so the truncation guard would have shipped as a test no gate
ever runs -- green on my machine, invisible to closeout and to every future
regression. Caught while re-verifying after amendment 2 cleared the receipt.

This is a WIRING CORRECTION, not new scope: no new files, no new behaviour, the
test already exists and already passes. Recorded as a third amendment anyway,
because the alternative is editing required_checks quietly, and the whole point
of amendment 2's note was that scope changes stay visible to a reviewer.

## Amendment 4 2026-08-06: bypass_check omitted the security property

The registered bypass_check was `-k 'invalid or duplicate or timestamp'`, which
selects 6 of 23 tests. It omitted `test_corrupt_line_cannot_hide_a_blocking_item_from_the_gate`
-- the test this file's own docstring calls "THE security property" -- plus every
write-validation test, the fleet-status tests, and both decode tests.

bypass_check is the PERMANENT regression gate registered at closeout, so a
`-k` filter written before most of the tests existed becomes a gate that
re-proves a fraction of what it claims. Now runs both files in full.

Found by adversarial review, which named it while explicitly declining to file
it (outside the contract slice). Fourth amendment, recorded like the others.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Implement the validated latest-event fold

## Amendments

### 2026-08-06T17:06:42Z
Reason: prd_runner.py moved to allowed_files: the validated fold must replace the silent JSONDecodeError skip in _read_spillover, the single chokepoint every ledger reader goes through. Without it the module ships inert.

Before:
- allowed_files: ['plugins/prd-os/scripts/spillover_events.py', 'plugins/prd-os/schemas/spillover-event.schema.json', 'plugins/prd-os/tests/test_spillover_events.py']
- required_checks: ['python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py']
- disallowed_files: ['.prd-os/spillover.jsonl', 'plugins/prd-os/scripts/prd_runner.py', 'q-system/**', '.git/**']

After:
- allowed_files: ['plugins/prd-os/scripts/spillover_events.py', 'plugins/prd-os/schemas/spillover-event.schema.json', 'plugins/prd-os/tests/test_spillover_events.py', 'plugins/prd-os/scripts/prd_runner.py']
- required_checks: ['python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py']
- disallowed_files: ['.prd-os/spillover.jsonl', 'q-system/**', '.git/**']

### 2026-08-06T17:38:00Z
Reason: findings_writer.py + its test added: this issue already owns the ledger write path (validate_for_append gating _spillover_append). findings_writer calls that same chokepoint and feeds it a body truncated to 120 chars, writing structurally-valid but information-lossy events. sp-9f11cf69. Second amendment, recorded loudly so scope drift is visible.

Before:
- allowed_files: ['plugins/prd-os/scripts/spillover_events.py', 'plugins/prd-os/schemas/spillover-event.schema.json', 'plugins/prd-os/tests/test_spillover_events.py', 'plugins/prd-os/scripts/prd_runner.py']
- required_checks: ['python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py']
- disallowed_files: ['.prd-os/spillover.jsonl', 'q-system/**', '.git/**']

After:
- allowed_files: ['plugins/prd-os/scripts/spillover_events.py', 'plugins/prd-os/schemas/spillover-event.schema.json', 'plugins/prd-os/tests/test_spillover_events.py', 'plugins/prd-os/scripts/prd_runner.py', 'plugins/prd-os/scripts/findings_writer.py', 'plugins/prd-os/tests/test_findings_writer_body.py']
- required_checks: ['python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py']
- disallowed_files: ['.prd-os/spillover.jsonl', 'q-system/**', '.git/**']

### 2026-08-06T17:46:06Z
Reason: WIRING CORRECTION: required_checks was missing test_findings_writer_body.py, which amendment 2 added to allowed_files. The truncation guard would have shipped as a test no gate runs. No new files or behaviour.

Before:
- allowed_files: ['plugins/prd-os/scripts/spillover_events.py', 'plugins/prd-os/schemas/spillover-event.schema.json', 'plugins/prd-os/tests/test_spillover_events.py', 'plugins/prd-os/scripts/prd_runner.py', 'plugins/prd-os/scripts/findings_writer.py', 'plugins/prd-os/tests/test_findings_writer_body.py']
- required_checks: ['python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py']
- disallowed_files: ['.prd-os/spillover.jsonl', 'q-system/**', '.git/**']

After:
- allowed_files: ['plugins/prd-os/scripts/spillover_events.py', 'plugins/prd-os/schemas/spillover-event.schema.json', 'plugins/prd-os/tests/test_spillover_events.py', 'plugins/prd-os/scripts/prd_runner.py', 'plugins/prd-os/scripts/findings_writer.py', 'plugins/prd-os/tests/test_findings_writer_body.py']
- required_checks: ['python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py', 'python3 -m pytest -q plugins/prd-os/tests/test_findings_writer_body.py']
- disallowed_files: ['.prd-os/spillover.jsonl', 'q-system/**', '.git/**']

### 2026-08-06T18:05:48Z
Reason: WIRING CORRECTION: bypass_check -k filter selected 6 of 23 tests and omitted the security-property test plus all write-validation, fleet-status and decode tests. Now runs both test files in full. No new files or behaviour.

Before:
- allowed_files: ['plugins/prd-os/scripts/spillover_events.py', 'plugins/prd-os/schemas/spillover-event.schema.json', 'plugins/prd-os/tests/test_spillover_events.py', 'plugins/prd-os/scripts/prd_runner.py', 'plugins/prd-os/scripts/findings_writer.py', 'plugins/prd-os/tests/test_findings_writer_body.py']
- required_checks: ['python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py', 'python3 -m pytest -q plugins/prd-os/tests/test_findings_writer_body.py']
- disallowed_files: ['.prd-os/spillover.jsonl', 'q-system/**', '.git/**']

After:
- allowed_files: ['plugins/prd-os/scripts/spillover_events.py', 'plugins/prd-os/schemas/spillover-event.schema.json', 'plugins/prd-os/tests/test_spillover_events.py', 'plugins/prd-os/scripts/prd_runner.py', 'plugins/prd-os/scripts/findings_writer.py', 'plugins/prd-os/tests/test_findings_writer_body.py']
- required_checks: ['python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py', 'python3 -m pytest -q plugins/prd-os/tests/test_findings_writer_body.py']
- disallowed_files: ['.prd-os/spillover.jsonl', 'q-system/**', '.git/**']
