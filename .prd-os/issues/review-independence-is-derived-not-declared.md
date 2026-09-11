---
id: review-independence-is-derived-not-declared
title: Review independence is a derived property, not the degraded cause-flag
status: open
priority: p1
parent_prd: null
blocked_by: "PR #114 (ASK-287) must land first: reviewed_by/degraded do not exist on main yet"
allowed_files:
  - q-system/.q-system/scripts/pr-review-agent.sh
  - q-system/.q-system/scripts/verify-codex-review-live.sh
  - q-system/.q-system/scripts/test/test-review-degraded-provenance.sh
  - q-system/.q-system/scripts/test/test-review-independence-property.sh
  - q-system/.q-system/capability-manifest.json
disallowed_files:
  - q-system/.q-system/scripts/converge.sh
  - q-system/.q-system/scripts/linear-worker.sh
  - .prd-os/**
  - plugins/**
  - instance-registry.json
required_checks:
  - bash q-system/.q-system/scripts/test/test-review-independence-property.sh
  - bash q-system/.q-system/scripts/test/test-review-degraded-provenance.sh
  - bash q-system/.q-system/scripts/test/test-review-invoker-provenance.sh
  - bash q-system/.q-system/scripts/test/test-review-comment-body.sh
required_reviews:
  - reviewer-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-review-independence-property.sh && bash q-system/.q-system/scripts/test/test-review-degraded-provenance.sh"
deliverables_count: 3
---

# Review independence is a derived property, not the degraded cause-flag

## Context

`degraded` encodes a CAUSE — "codex was asked and failed" — while every consumer
reads it for a PROPERTY: "is this review an independent second opinion?" Those
two come apart on a path that already exists.

Found by the DEGRADED claude reviewer on PR #114 (finding 3), plus `sp-cc2de280`
from the consumer end. One defect, two halves.

**The writer half.** A deliberate `--engine claude` run records `degraded: false`
because codex was never asked, so nothing failed. But an Opus review is not a
second lab's opinion regardless of why it happened. The consumer reference in
`test-review-degraded-provenance.sh` maps `degraded == false` to `independent`,
so a deliberate Opus review reads as independent. `--engine claude` is a live
path (arg parser), and with `KIPI_REVIEW_PRIMARY_ENGINE=claude` that engine
writes the ROOT gating record.

**The reader half (`sp-cc2de280`).** `verify-codex-review-live.sh` selects
receipts on `r.get("engine") != "codex": continue` and then reports
`RECEIPT FOUND: a codex-engine review really ran`. A DEGRADED Opus record also
carries `engine: codex`, so the live-proof check is satisfiable by a review codex
never wrote. That is a consumer reading the cause field for the property, at the
one check whose entire job is proving codex is alive.

**Time pressure.** Codex is out of credits until 2026-08-09. Every review until
then runs the fallback. Until this lands, the live-proof check will certify
reviews codex never wrote.

## The invariant

`independent` is TRUE only when the model that actually produced the prose
belongs to a different lab than the primary engine. Derive it from `reviewed_by`
vs `PRIMARY_ENGINE`, not from `degraded`, and not from `engine`.

**DERIVED AND RECOMPUTED AT READ TIME, NEVER STORED AS A CLAIM.** A stored
`independent: true` is the same defect one turn later: a field asserting a
property nothing recomputed, believed by the next reader. `reviewed_by` is an
observation (which model ran); independence is a judgement ABOUT that
observation, and judgements go stale when the primary engine changes. If a
record must carry it for cheap consumption, it is a convenience cache and the
reader still recomputes and refuses on disagreement.

## Reproducer (must go RED first, both halves)

Neither of these can pass before the fix. Write them, watch them fail, then fix.

1. **Deliberate Opus reads as independent.** Write a record via the shipped
   writer with `ENGINE=claude`, `DEGRADED=0`. Assert the independence consumer
   answers NOT independent. Pre-fix it answers `independent` (because
   `degraded` is false) — that is the red.
2. **Live-proof check accepts a degraded Opus record.** Build a verdict record
   with `engine: codex`, `degraded: true`, `reviewed_by: claude-opus-5`, point
   `verify-codex-review-live.sh` at a fixture state dir, and assert it does NOT
   report a codex receipt. Pre-fix it reports
   `RECEIPT FOUND: a codex-engine review really ran` — that is the red.

Both must be driven against the SHIPPED code (extract the writer / run the real
script against a fixture dir), never a reimplementation.

## Mutation bar

Each assertion killed by its own mutant, neither masking the other:

- remove the independence derivation → case 1 red, case 2 green
- revert the live-proof selector to `engine == "codex"` alone → case 2 red,
  case 1 green
- validate every mutant actually applied before reading its result
- confirm the anchor survives when the mutant edits near an extraction anchor
  (a suite that exits 1 from its own extraction guard is not a case-level kill)

## Fail-safe direction

A record with no `reviewed_by` (every record written before PR #114) is UNKNOWN,
never independent. Same direction the existing `invoker` handling already takes:
absence is not evidence.

## Note on `bypass_check`

The bypass_check above runs BOTH suites in full and does not use `-k` or any
selector. This is deliberate. A bypass_check that selects a subset can silently
omit the security-relevant case — the other Sana found one selecting 6 of 23
tests with the security-property test among the 17 omitted, and an unquoted `-k`
in this repo once meant zero tests ran while the harness reported perfect
survival. If this check ever needs narrowing, the narrowing must be proven to
still include case 1 and case 2 above by deleting each and watching it go red.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Derive `independent` from `reviewed_by` vs primary engine; recompute at read time, never trust a stored flag
- [ ] Fix `verify-codex-review-live.sh` to consult the derived property, treating a missing key as UNKNOWN
- [ ] `test-review-independence-property.sh` with both reproducers, registered in the capability manifest
