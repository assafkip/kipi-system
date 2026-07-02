---
description: Sycophancy enforcement wiring for kipi instances
paths:
  - "q-system/.q-system/agent-pipeline/**"
  - "q-system/canonical/decisions.md"
  - "q-system/output/**"
---

# Sycophancy (ENFORCED by wired scripts)

The behavioral rules, the origin-tag vocabulary, and the pi metric live in
`sycophancy-core.md` — the portable core, safe to ship to systems that have no
kipi pipeline (huntkit gets that file, not this one). This file is the kipi
enforcement wiring:

- **Write-time:** the `decision-origin-tag-lint.py` PostToolUse hook blocks an
  untagged decision written to `canonical/decisions.md`.
- **Any time:** `python3 q-system/.q-system/sycophancy-harness.py --standalone`
  recomputes pi from the decision log alone — no pipeline artifacts needed.
  Exit 1 when pi >= 0.7 with >= 5 tagged assistant-recommended decisions.
- **Monthly:** the `sycophancy-monthly-check.py` SessionStart hook script runs
  the standalone check on the first session of each month and surfaces the
  verdict. This is the deterministic form of core's "review it monthly" line.
- **Morning pipeline:** the Phase-6 audit agent and its verification rules live
  in `morning-pipeline.md`.

## Scar

2026-07-01: the pi check only ever executed inside /q-morning, gated on a bus
artifact. An instance ran at pi~=0.88 — past the 0.7 alert line — and nothing
could notice, because that instance never runs the morning pipeline. Hence the
standalone mode and the monthly hook.
