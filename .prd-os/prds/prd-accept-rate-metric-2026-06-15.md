---
id: prd-accept-rate-metric-2026-06-15
title: Accept Rate Metric
status: in-review
created_at: 2026-06-15T22:54:44Z
updated_at: 2026-06-15T22:59:34Z
owner: assafkip
reviewers: []
findings_path: .prd-os/findings/prd-accept-rate-metric-2026-06-15-findings.jsonl
codex_reviewed_at: 2026-06-15T23:39:35Z
---

# Accept Rate Metric

## Problem

Before this, there was no way to see when work got marked done with no receipt
proving it actually happened. The fleet counts effort (turns completed), not
whether the gate's objections get fixed. Confirmed by the author 2026-06-15.

Observed proof: PRD `prd-build-craft-2026-06-15` sits in-review with 8 accepted
findings and zero receipts, plus 4 deferred-major findings. Three other PRDs in
`.prd-os/` are clean. Nothing in the system surfaced that gap until this tool ran.

## Goals

- Per PRD, report disposition mix, deferred-major rate, and accepted-without-receipt count
- Deterministic and read-only: a script reading the trail, not a model judging itself
- `--gate` exit-code 2 on any alert, so it can wire into a hook later

## Non-goals

- Token / dollar cost per change. Fleet tokens are effectively unmetered, so cost is the wrong denominator.
- An LLM-as-judge. The whole point is a check the model cannot talk itself past.

## Proposed approach

Already built at `q-system/.q-system/scripts/accept-rate.py`. Reads
`.prd-os/findings/*.jsonl` and `.prd-os/receipts.jsonl`. A finding is receipted
when `(prd_id, finding_id)` appears in `receipts.jsonl`. Two signals:

```
deferred-major            -> the gate objected and we waved it
accepted-without-receipt  -> we said we'd fix it; no receipt it happened
```

A PRD alerts when accepted-without-receipt > 0 (hard, no threshold) or
deferred-major rate >= a tunable constant. Built following fable-discipline:
recon before edit, a `--selftest` with a negative case run only against a tempdir
copy, scar-anchored comments, stdlib only.

## Risks and rollback

Read-only script. No mutation of any shared resource, so blast radius is near
zero. The deferred-major threshold is a tunable constant, not a truth claim.
Rollback is deleting one file.

## Open questions

- Wiring surface: a `kipi_accept_rate` MCP tool vs a call from `/q-wrap`
- Threshold calibration after a few weeks of real output
- Should accepted-without-receipt become a hard gate (exit 2) in a CI/pre-archive check

## Issues

```json
[
  {
    "id": "accept-rate-metric-script",
    "title": "accept-rate.py prd-os disposition/receipt-coverage metric",
    "allowed_files": ["q-system/.q-system/scripts/accept-rate.py"],
    "required_checks": ["python3 q-system/.q-system/scripts/accept-rate.py --selftest"],
    "acceptance": "selftest passes (positive+negative); plain run flags build-craft (8 accepted / 0 receipts) and leaves the other 3 PRDs ok; --gate exits 2 on alert"
  }
]
```
