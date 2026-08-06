---
id: scs-lifecycle-events
title: Append closure, supersession, void, and severity events
status: open
priority: p2
parent_prd: prd-spillover-current-state-2026-07-24
allowed_files:
  - plugins/prd-os/scripts/prd_runner.py
  - plugins/prd-os/tests/test_spillover_lifecycle.py
disallowed_files:
  - .prd-os/spillover.jsonl
  - plugins/prd-os/schemas/**
  - q-system/**
  - .git/**
required_checks:
  - python3 -m pytest -q plugins/prd-os/tests/test_spillover_lifecycle.py
required_reviews:
  - prd-os-owner
bypass_check: "python3 -m pytest -q plugins/prd-os/tests/test_spillover_lifecycle.py -k 'stale or severity or mutate'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-spillover-current-state-2026-07-24 finding=finding-2 at=2026-07-24T21:14:34Z -->

# Append closure, supersession, void, and severity events

## Context

Parent PRD: `.prd-os/prds/prd-spillover-current-state-2026-07-24.md`

## Acceptance

Write failing stale-status, severity-change, invalid-supersession, and history-mutation tests first. Express every correction as a new event.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Append closure, supersession, void, and severity events


## Reproducer available 2026-08-06 (scs-validated-event-fold session)

The description-correction event this issue must generalize has now been
performed TWICE by hand, so the mechanism is proven and only the VERB is
missing. The parent PRD already sanctions it, proposed approach item 2:
"Transitions retain the prior description and provenance unless a new event
explicitly changes them."

Two hand-run instances, both append-only, both preserving status and severity:

1. TRUNCATION RECOVERY (sp-9f11cf69). 3 open `defer-*` items whose bodies had
   been cut to 120 chars got a new event carrying the canonical body from
   `.prd-os/findings/<prd>-findings.jsonl`, with `description_recovered_at`,
   `description_recovered_from`, `description_prior_len`.
   Result: 149->260, 148->302, 148->372 chars, 0 permanently lossy.

2. CLAIM CORRECTION (sp-1e6af115). A proposal inside an item's description was
   refuted by measurement, so a new event carried the corrected text with
   `description_corrected_at`, `description_correction_reason`,
   `description_prior_len`. Result: 1606->3307 chars, status `open` and
   severity `medium` both preserved.

WHAT THIS ISSUE OWES. Those two used DIFFERENT provenance vocabularies
(`_recovered_*` vs `_corrected_*`) because each was invented at the point of
need. That is the derivation split this issue exists to close: ONE
`description_changed` event type, one provenance shape, one CLI verb, so a
correction is not a hand-written python block each time.

WHY IT MATTERS BEYOND TIDINESS. Without a verb, an agent that discovers its own
recorded claim is wrong faces a choice between leaving the wrong claim standing
and filing a new item that duplicates the old one. Both are bad; the first is
how a ledger accumulates statements nobody believes. Observed live this session.
